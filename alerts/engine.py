"""
Alert evaluation engine — checks scores against thresholds and decides
which alerts to fire. Does NOT deliver alerts — that's slack.py's job.

Evaluates four condition types from available data:
- CRITICAL / high_score_active: account score > 80
- CRITICAL / reengagement_window: dark 30+ days then 2+ signals in last 7 days
- HIGH / untouched_high_score: score > 60, no signals in last 48 hours
- STANDARD / morning_digest: top 5 accounts per rep by score

Respects:
- Max real-time alerts per rep per day (default 3)
- Account snooze from account_preferences
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pipeline.scorer import AccountScore, SignalContribution


@dataclass
class Alert:
    """One alert to be delivered."""
    alert_id: str
    account_id: str
    account_name: str
    rep_id: str
    alert_tier: str          # CRITICAL, HIGH, STANDARD
    alert_type: str          # high_score_active, reengagement_window, untouched_high_score, morning_digest
    score_at_fire: float
    score_breakdown_snapshot: list[dict]
    channel: str             # slack_dm, mcp, digest
    title: str
    body: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tribal_pattern_text: str | None = None
    velocity_applied: bool = False
    velocity_multiplier: float = 1.0
    rep_feedback: str | None = None       # correct, incorrect, or None
    feedback_text: str | None = None


class AlertEngine:
    """Evaluates scores against thresholds. Produces alerts."""

    def __init__(self, config: dict):
        self.config = config
        self.tiers = config.get("tiers", {})
        self.settings = config.get("settings", {})
        self.max_realtime = self.settings.get("max_realtime_alerts_per_rep_per_day", 3)

    def evaluate(
        self,
        scores: list[AccountScore],
        signals_by_account: dict[str, list],
        rep_accounts: dict[str, set[str]],
        account_map: dict[str, dict],
        snoozed_accounts: set[str],
        as_of: datetime,
        existing_alert_counts: dict[str, int] | None = None,
    ) -> list[Alert]:
        """
        Evaluate all scored accounts and return alerts to fire.

        Args:
            scores: Scored accounts from ScoringEngine, sorted by final_score desc.
            signals_by_account: Raw signal events grouped by account_id.
            rep_accounts: Map of rep_id → set of account_ids they own.
            account_map: Account metadata keyed by account Id.
            snoozed_accounts: Account IDs currently snoozed.
            as_of: Reference datetime for evaluation.
            existing_alert_counts: Optional dict of rep_id → alerts already fired today.
        """
        # Build reverse map: account_id → rep_id
        account_to_rep: dict[str, str] = {}
        for rep_id, acct_ids in rep_accounts.items():
            for acct_id in acct_ids:
                account_to_rep[acct_id] = rep_id

        # Track alerts fired per rep this evaluation
        rep_alert_counts: dict[str, int] = dict(existing_alert_counts or {})

        # Score lookup
        score_map = {s.account_id: s for s in scores}

        alerts: list[Alert] = []
        alert_counter = 0

        # --- CRITICAL and HIGH: per-account evaluation ---
        for score in scores:
            acct_id = score.account_id
            if acct_id in snoozed_accounts:
                continue

            rep_id = account_to_rep.get(acct_id, "")
            if not rep_id:
                continue

            acct = account_map.get(acct_id, {})
            acct_name = acct.get("Name", acct_id)
            acct_signals = signals_by_account.get(acct_id, [])
            breakdown = self._build_breakdown_snapshot(score)

            # CRITICAL: high_score_active (score > 80)
            critical_cfg = self.tiers.get("CRITICAL", {})
            critical_conditions = critical_cfg.get("conditions", [])
            high_score_cond = next((c for c in critical_conditions if c["type"] == "high_score_active"), None)
            min_critical_score = high_score_cond["min_score"] if high_score_cond else 80

            if score.final_score > min_critical_score:
                if self._can_fire_realtime(rep_id, rep_alert_counts):
                    alert_counter += 1
                    alerts.append(Alert(
                        alert_id=f"alert_rt_{alert_counter:04d}",
                        account_id=acct_id,
                        account_name=acct_name,
                        rep_id=rep_id,
                        alert_tier="CRITICAL",
                        alert_type="high_score_active",
                        score_at_fire=score.final_score,
                        score_breakdown_snapshot=breakdown,
                        channel="slack_dm",
                        title=f"High-score signal on {acct_name}",
                        body=f"Score {score.final_score:.0f} — active account with strong buying signals.",
                        timestamp=as_of,
                        tribal_pattern_text=score.tribal_pattern_text,
                        velocity_applied=score.velocity_applied,
                        velocity_multiplier=score.velocity_multiplier,
                    ))
                    rep_alert_counts[rep_id] = rep_alert_counts.get(rep_id, 0) + 1
                    continue  # Don't double-alert same account

            # CRITICAL: reengagement_window
            if self._check_reengagement(acct_signals, as_of):
                if self._can_fire_realtime(rep_id, rep_alert_counts):
                    alert_counter += 1
                    alerts.append(Alert(
                        alert_id=f"alert_rt_{alert_counter:04d}",
                        account_id=acct_id,
                        account_name=acct_name,
                        rep_id=rep_id,
                        alert_tier="CRITICAL",
                        alert_type="reengagement_window",
                        score_at_fire=score.final_score,
                        score_breakdown_snapshot=breakdown,
                        channel="slack_dm",
                        title=f"Re-engagement window detected — {acct_name}",
                        body=f"Account went dark 30+ days then showed 2+ signals in the last 7 days. Score: {score.final_score:.0f}.",
                        timestamp=as_of,
                        tribal_pattern_text=score.tribal_pattern_text,
                        velocity_applied=score.velocity_applied,
                        velocity_multiplier=score.velocity_multiplier,
                    ))
                    rep_alert_counts[rep_id] = rep_alert_counts.get(rep_id, 0) + 1
                    continue

            # HIGH: untouched_high_score (score > 60, no signals in last 48h)
            high_cfg = self.tiers.get("HIGH", {})
            high_conditions = high_cfg.get("conditions", [])
            untouched_cond = next((c for c in high_conditions if c["type"] == "untouched_high_score"), None)
            min_high_score = untouched_cond["min_score"] if untouched_cond else 60
            untouched_hours = untouched_cond["untouched_hours"] if untouched_cond else 48

            if score.final_score > min_high_score:
                if self._check_untouched(acct_signals, as_of, untouched_hours):
                    if self._can_fire_realtime(rep_id, rep_alert_counts):
                        alert_counter += 1
                        alerts.append(Alert(
                            alert_id=f"alert_rt_{alert_counter:04d}",
                            account_id=acct_id,
                            account_name=acct_name,
                            rep_id=rep_id,
                            alert_tier="HIGH",
                            alert_type="untouched_high_score",
                            score_at_fire=score.final_score,
                            score_breakdown_snapshot=breakdown,
                            channel="slack_dm",
                            title=f"Untouched high-score account — {acct_name}",
                            body=f"Score {score.final_score:.0f} with no signals in the last {untouched_hours} hours. Time to reach out.",
                            timestamp=as_of,
                            tribal_pattern_text=score.tribal_pattern_text,
                            velocity_applied=score.velocity_applied,
                            velocity_multiplier=score.velocity_multiplier,
                        ))
                        rep_alert_counts[rep_id] = rep_alert_counts.get(rep_id, 0) + 1

        # --- STANDARD: morning digest (top 5 per rep) ---
        std_cfg = self.tiers.get("STANDARD", {})
        std_conditions = std_cfg.get("conditions", [])
        digest_cond = next((c for c in std_conditions if c["type"] == "morning_digest"), None)
        top_n = digest_cond["top_n"] if digest_cond else 5

        for rep_id, acct_ids in rep_accounts.items():
            rep_scores = [
                s for s in scores
                if s.account_id in acct_ids and s.account_id not in snoozed_accounts
            ]
            # Already sorted by final_score desc
            top_accounts = rep_scores[:top_n]
            if not top_accounts:
                continue

            digest_lines = []
            for rank, s in enumerate(top_accounts, 1):
                acct = account_map.get(s.account_id, {})
                name = acct.get("Name", s.account_id)
                top_reason = ""
                if s.score_breakdown:
                    top_contrib = max(s.score_breakdown, key=lambda c: abs(c.decayed_weight))
                    top_reason = top_contrib.reason_text
                digest_lines.append(f"{rank}. {name} — Score {s.final_score:.0f} — {top_reason}")

            alert_counter += 1
            alerts.append(Alert(
                alert_id=f"alert_dg_{alert_counter:04d}",
                account_id="digest",
                account_name="Morning Digest",
                rep_id=rep_id,
                alert_tier="STANDARD",
                alert_type="morning_digest",
                score_at_fire=top_accounts[0].final_score if top_accounts else 0,
                score_breakdown_snapshot=[
                    {
                        "account_id": s.account_id,
                        "account_name": account_map.get(s.account_id, {}).get("Name", s.account_id),
                        "final_score": s.final_score,
                        "top_signals": self._build_breakdown_snapshot(s)[:3],
                        "velocity_applied": s.velocity_applied,
                        "tribal_pattern_text": s.tribal_pattern_text,
                    }
                    for s in top_accounts
                ],
                channel="digest",
                title="Morning Digest — Your Top Accounts",
                body="\n".join(digest_lines),
                timestamp=as_of,
            ))

        return alerts

    def _build_breakdown_snapshot(self, score: AccountScore) -> list[dict]:
        """Build a JSON-serializable snapshot of the top 5 signal contributions."""
        top = sorted(score.score_breakdown, key=lambda c: abs(c.decayed_weight), reverse=True)[:5]
        return [
            {
                "signal_type": c.signal_type,
                "raw_weight": c.raw_weight,
                "decayed_weight": round(c.decayed_weight, 1),
                "reason_text": c.reason_text,
                "triggered_at": c.triggered_at.isoformat(),
                "decay_factor": round(c.decay_factor, 3),
            }
            for c in top
        ]

    def _can_fire_realtime(self, rep_id: str, counts: dict[str, int]) -> bool:
        """Check if this rep is under the max real-time alerts per day limit."""
        return counts.get(rep_id, 0) < self.max_realtime

    def _check_reengagement(self, signals: list, as_of: datetime) -> bool:
        """
        Re-engagement window: account had no signals for 30+ days,
        then got 2+ signals in the last 7 days.
        """
        if not signals:
            return False

        recent_cutoff = as_of - timedelta(days=7)
        dark_cutoff = as_of - timedelta(days=37)  # 30 days before the 7-day window

        recent_signals = [s for s in signals if s.triggered_at >= recent_cutoff]
        if len(recent_signals) < 2:
            return False

        # Check for a gap: no signals between dark_cutoff and recent_cutoff
        gap_signals = [
            s for s in signals
            if dark_cutoff <= s.triggered_at < recent_cutoff
        ]
        return len(gap_signals) == 0

    def _check_untouched(self, signals: list, as_of: datetime, hours: int) -> bool:
        """Check if account has no signals in the last N hours."""
        if not signals:
            return True
        cutoff = as_of - timedelta(hours=hours)
        recent = [s for s in signals if s.triggered_at >= cutoff]
        return len(recent) == 0


def get_snoozed_accounts(preferences: list[dict], as_of: datetime) -> set[str]:
    """Return account IDs currently snoozed (not expired as of as_of)."""
    snoozed = set()
    for pref in preferences:
        if pref["preference_type"] != "snooze":
            continue
        expires = pref.get("expires_date", "")
        if expires:
            exp_date = datetime.fromisoformat(expires).replace(tzinfo=timezone.utc)
            if exp_date < as_of:
                continue  # Expired
        snoozed.add(pref["account_id"])
    return snoozed


def load_historical_alerts(alert_log: list[dict]) -> list[Alert]:
    """Convert pre-generated alert_log.json records into Alert objects."""
    alerts = []
    for record in alert_log:
        alerts.append(Alert(
            alert_id=record.get("id", ""),
            account_id=record.get("account_id", ""),
            account_name="",  # Not in alert_log data
            rep_id=record.get("rep_id", ""),
            alert_tier=record.get("tier", "STANDARD"),
            alert_type=record.get("alert_type", ""),
            score_at_fire=0,  # Not in alert_log data
            score_breakdown_snapshot=[],
            channel="slack_dm" if record.get("tier") != "STANDARD" else "digest",
            title=record.get("title", ""),
            body=record.get("body", ""),
            timestamp=datetime.fromisoformat(record["timestamp"]).replace(tzinfo=timezone.utc) if record.get("timestamp") else datetime.now(timezone.utc),
            rep_feedback="correct" if record.get("responded") else None,
        ))
    return alerts
