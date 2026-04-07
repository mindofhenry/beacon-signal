"""
Slack bot for Signal alert delivery — separate process from Intel's bot.

Shares the same Slack app tokens (SLACK_BOT_TOKEN, SLACK_APP_TOKEN) but runs
independently using Socket Mode. Intel handles #ask-beacon Q&A; Signal handles
DM alerts and digest delivery. No collision.

If SLACK_BOT_TOKEN is missing or set to a placeholder, falls back to console
output so formatting and logic can be validated without a live Slack workspace.

Usage:
    python -m alerts.slack              # run as module from repo root
    python alerts/slack.py              # run directly
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from pipeline.adapters.job_change import JobChangeAdapter
from pipeline.adapters.intent_surge import IntentSurgeAdapter
from pipeline.adapters.engagement import EngagementAdapter
from pipeline.adapters.funding_growth import FundingGrowthAdapter
from pipeline.config import load_weights_config, load_alert_config
from pipeline.data_loader import DataLoader
from pipeline.scorer import ScoringEngine

from alerts.engine import AlertEngine, Alert, get_snoozed_accounts
from alerts.formatter import (
    format_realtime_blocks,
    format_realtime_text,
    format_digest_blocks,
    format_digest_text,
    SF_BASE_URL,
)


# ---------------------------------------------------------------------------
# Demo mode constants
# ---------------------------------------------------------------------------

DEMO_AS_OF = datetime(2026, 3, 31, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Shared state — loaded at startup
# ---------------------------------------------------------------------------

class SignalState:
    """Server-wide state: scores, signals, alert engine."""

    def __init__(self):
        self.config = load_weights_config()
        self.alert_config = load_alert_config()
        self.loader = DataLoader()
        self.engine = ScoringEngine(self.config)
        self.alert_engine = AlertEngine(self.alert_config)

        # Load signals via adapters
        adapters = [
            JobChangeAdapter(self.config),
            IntentSurgeAdapter(self.config),
            EngagementAdapter(self.config),
            FundingGrowthAdapter(self.config),
        ]
        self.all_signals = []
        for adapter in adapters:
            self.all_signals.extend(adapter.fetch_signals())

        # Group by account
        self.signals_by_account: dict[str, list] = defaultdict(list)
        for s in self.all_signals:
            self.signals_by_account[s.account_id].append(s)

        # Score
        self.scores = self.engine.score_accounts(self.all_signals, as_of=DEMO_AS_OF)
        self.score_map = {s.account_id: s for s in self.scores}
        self.account_map = self.loader.get_account_map()

        # Rep → accounts via opportunities
        self.rep_accounts: dict[str, set[str]] = defaultdict(set)
        for opp in self.loader.get_opportunities():
            owner = opp.get("OwnerId", "")
            acct = opp.get("AccountId", "")
            if owner and acct:
                self.rep_accounts[owner].add(acct)

        # Snoozed accounts
        preferences = self.loader.get_account_preferences()
        self.snoozed = get_snoozed_accounts(preferences, DEMO_AS_OF)

        # Rep lookup
        self.reps = {r["id"]: r for r in self.loader.get_reps()}

        # In-memory alert log
        self.alert_log: list[Alert] = []
        self.daily_alert_counts: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Console fallback — used when Slack tokens are missing
# ---------------------------------------------------------------------------

class ConsoleDelivery:
    """Prints alerts to console instead of sending via Slack."""

    def deliver_realtime(self, alert: Alert, state: SignalState):
        rep = state.reps.get(alert.rep_id, {})
        rep_name = rep.get("name", alert.rep_id)
        print(f"\n{'='*60}")
        print(f"  DM to {rep_name} ({alert.rep_id})")
        print(f"{'='*60}")
        print(format_realtime_text(alert))
        print(f"{'='*60}\n")

    def deliver_digest(self, alert: Alert, state: SignalState):
        rep = state.reps.get(alert.rep_id, {})
        rep_name = rep.get("name", alert.rep_id)
        print(f"\n{'='*60}")
        print(f"  Morning Digest for {rep_name} ({alert.rep_id})")
        print(f"{'='*60}")
        print(format_digest_text(alert))
        print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Slack delivery — used when tokens are available
# ---------------------------------------------------------------------------

class SlackDelivery:
    """Sends alerts via Slack DM using slack_bolt."""

    def __init__(self, app):
        self.app = app
        self._dm_channels: dict[str, str] = {}

    def _get_dm_channel(self, rep_id: str, state: SignalState) -> str | None:
        """Open a DM channel with the rep. Caches channel IDs."""
        if rep_id in self._dm_channels:
            return self._dm_channels[rep_id]

        rep = state.reps.get(rep_id, {})
        email = rep.get("email", "")
        if not email:
            return None

        try:
            result = self.app.client.users_lookupByEmail(email=email)
            user_id = result["user"]["id"]
            dm = self.app.client.conversations_open(users=[user_id])
            channel_id = dm["channel"]["id"]
            self._dm_channels[rep_id] = channel_id
            return channel_id
        except Exception as e:
            print(f"[Signal] Could not open DM for {rep_id} ({email}): {e}")
            return None

    def deliver_realtime(self, alert: Alert, state: SignalState):
        channel = self._get_dm_channel(alert.rep_id, state)
        if not channel:
            print(f"[Signal] No DM channel for {alert.rep_id}, falling back to console")
            ConsoleDelivery().deliver_realtime(alert, state)
            return

        blocks = format_realtime_blocks(alert)
        fallback = f"{alert.alert_tier}: {alert.title} — Score {alert.score_at_fire:.0f}"

        try:
            self.app.client.chat_postMessage(
                channel=channel,
                text=fallback,
                blocks=blocks,
            )
        except Exception as e:
            print(f"[Signal] Failed to send DM to {alert.rep_id}: {e}")

    def deliver_digest(self, alert: Alert, state: SignalState):
        channel = self._get_dm_channel(alert.rep_id, state)
        if not channel:
            print(f"[Signal] No DM channel for {alert.rep_id}, falling back to console")
            ConsoleDelivery().deliver_digest(alert, state)
            return

        blocks = format_digest_blocks(alert)
        fallback = "Morning Digest — Your Top Accounts"

        try:
            self.app.client.chat_postMessage(
                channel=channel,
                text=fallback,
                blocks=blocks,
            )
        except Exception as e:
            print(f"[Signal] Failed to send digest to {alert.rep_id}: {e}")


# ---------------------------------------------------------------------------
# Core alert functions
# ---------------------------------------------------------------------------

def fire_demo_alerts(state: SignalState, delivery) -> list[Alert]:
    """
    Evaluate current scores and fire CRITICAL/HIGH alerts.
    Returns the alerts that were fired.
    """
    alerts = state.alert_engine.evaluate(
        scores=state.scores,
        signals_by_account=state.signals_by_account,
        rep_accounts=state.rep_accounts,
        account_map=state.account_map,
        snoozed_accounts=state.snoozed,
        as_of=DEMO_AS_OF,
        existing_alert_counts=state.daily_alert_counts,
    )

    realtime = [a for a in alerts if a.alert_tier in ("CRITICAL", "HIGH")]
    for alert in realtime:
        delivery.deliver_realtime(alert, state)
        state.alert_log.append(alert)
        state.daily_alert_counts[alert.rep_id] = state.daily_alert_counts.get(alert.rep_id, 0) + 1

    print(f"\n[Signal] Fired {len(realtime)} real-time alerts "
          f"({sum(1 for a in realtime if a.alert_tier == 'CRITICAL')} CRITICAL, "
          f"{sum(1 for a in realtime if a.alert_tier == 'HIGH')} HIGH)")

    return alerts


def fire_morning_digest(state: SignalState, delivery) -> list[Alert]:
    """
    Generate and send morning digest for all reps.
    Returns the digest alerts.
    """
    alerts = state.alert_engine.evaluate(
        scores=state.scores,
        signals_by_account=state.signals_by_account,
        rep_accounts=state.rep_accounts,
        account_map=state.account_map,
        snoozed_accounts=state.snoozed,
        as_of=DEMO_AS_OF,
        existing_alert_counts=state.daily_alert_counts,
    )

    digests = [a for a in alerts if a.alert_tier == "STANDARD"]
    for alert in digests:
        delivery.deliver_digest(alert, state)
        state.alert_log.append(alert)

    print(f"[Signal] Sent {len(digests)} morning digests")
    return digests


# ---------------------------------------------------------------------------
# Slack app setup (only when tokens available)
# ---------------------------------------------------------------------------

def create_slack_app(state: SignalState):
    """Create and configure the slack_bolt App with action handlers."""
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")

    app = App(token=bot_token)

    # --- Action: Looks right ---
    @app.action("alert_looks_right")
    def handle_looks_right(ack, body, client):
        ack()
        alert_id = body["actions"][0]["value"]
        user_id = body["user"]["id"]

        # Find alert in log and record feedback
        for alert in state.alert_log:
            if alert.alert_id == alert_id:
                alert.rep_feedback = "correct"
                break

        # Update the message to show feedback was recorded
        client.chat_update(
            channel=body["channel"]["id"],
            ts=body["message"]["ts"],
            text=f"Thanks for confirming! Feedback recorded as correct.",
            blocks=body["message"]["blocks"][:-1] + [{  # Remove action buttons
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"\u2705 *Confirmed as accurate* by <@{user_id}>"}]
            }]
        )

    # --- Action: Disagree ---
    @app.action("alert_disagree")
    def handle_disagree(ack, body, client):
        ack()
        alert_id = body["actions"][0]["value"]

        # Open feedback modal
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "disagree_feedback",
                "private_metadata": alert_id,
                "title": {"type": "plain_text", "text": "Alert Feedback"},
                "submit": {"type": "plain_text", "text": "Submit"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "feedback_block",
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "feedback_text",
                            "multiline": True,
                            "placeholder": {"type": "plain_text", "text": "What's wrong with this alert? What context is missing?"},
                        },
                        "label": {"type": "plain_text", "text": "What did we get wrong?"},
                    }
                ]
            }
        )

    # --- Modal submission: disagree feedback ---
    @app.view("disagree_feedback")
    def handle_feedback_submit(ack, body, client):
        ack()
        alert_id = body["view"]["private_metadata"]
        feedback = body["view"]["state"]["values"]["feedback_block"]["feedback_text"]["value"]
        user_id = body["user"]["id"]

        for alert in state.alert_log:
            if alert.alert_id == alert_id:
                alert.rep_feedback = "incorrect"
                alert.feedback_text = feedback
                break

        # DM the user to confirm
        try:
            dm = client.conversations_open(users=[user_id])
            client.chat_postMessage(
                channel=dm["channel"]["id"],
                text=f"Thanks for the feedback on alert `{alert_id}`. We'll use this to improve future scoring.",
            )
        except Exception:
            pass

    # --- Action: View in Salesforce ---
    @app.action("alert_view_sf")
    def handle_view_sf(ack, body, client):
        ack()
        account_id = body["actions"][0]["value"]
        sf_url = f"{SF_BASE_URL}/{account_id}"

        # Send ephemeral message with the link
        client.chat_postEphemeral(
            channel=body["channel"]["id"],
            user=body["user"]["id"],
            text=f"<{sf_url}|Open {account_id} in Salesforce>",
        )

    return app, SocketModeHandler(app, app_token)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    print("\nBeacon Signal — Alert Delivery Bot")
    print("=" * 40)

    # Initialize state
    print("Loading scoring data...")
    state = SignalState()
    print(f"  {len(state.scores)} accounts scored")
    print(f"  {len(state.snoozed)} accounts snoozed")
    print(f"  {len(state.rep_accounts)} reps with account assignments")

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")

    if bot_token and app_token and not bot_token.startswith("xoxb-placeholder"):
        # Live Slack mode
        print("\nSlack tokens found — starting Socket Mode bot...")
        app, handler = create_slack_app(state)
        delivery = SlackDelivery(app)

        # Fire demo alerts on startup
        print("\nFiring demo alerts...")
        fire_demo_alerts(state, delivery)

        print("\nBot is running. Press Ctrl+C to stop.\n")
        handler.start()
    else:
        # Console fallback
        print("\nNo Slack tokens — running in console mode.")
        print("Alerts will be printed to stdout.\n")
        delivery = ConsoleDelivery()

        # Fire demo alerts
        print("--- Real-time Alerts ---")
        fire_demo_alerts(state, delivery)

        print("\n--- Morning Digests ---")
        fire_morning_digest(state, delivery)

        print("\n[Signal] Console demo complete.")


if __name__ == "__main__":
    main()
