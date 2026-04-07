"""
Alert formatter — formats Alert objects into Slack Block Kit messages
and plain-text fallbacks.

Formats:
- CRITICAL / HIGH: rich DM with score breakdown, tribal callout, action buttons
- STANDARD (digest): numbered list of top accounts with one-line reasoning

Every alert includes the full score breakdown. No alert fires with just a number.
"""

from alerts.engine import Alert

# Tier emoji mapping
TIER_EMOJI = {
    "CRITICAL": "\U0001f534",   # Red circle
    "HIGH": "\U0001f7e1",       # Yellow circle
    "STANDARD": "\U0001f4cb",   # Clipboard
}

# Salesforce URL pattern (mock)
SF_BASE_URL = "https://doom-inc.my.salesforce.com"


def format_realtime_blocks(alert: Alert) -> list[dict]:
    """
    Format a CRITICAL or HIGH alert as Slack Block Kit blocks.
    Returns a list of block dicts ready for chat_postMessage(blocks=...).
    """
    emoji = TIER_EMOJI.get(alert.alert_tier, "\U0001f514")
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"{emoji} {alert.alert_tier} — {_alert_type_label(alert.alert_type)}",
            "emoji": True,
        }
    })

    # Account + score summary
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*{alert.account_name}*\nScore: *{alert.score_at_fire:.0f}* — here's why:",
        }
    })

    # Score breakdown (top 5 contributions)
    breakdown_lines = []
    for contrib in alert.score_breakdown_snapshot[:5]:
        weight = contrib.get("decayed_weight", 0)
        reason = contrib.get("reason_text", contrib.get("signal_type", ""))
        sign = "+" if weight >= 0 else ""
        breakdown_lines.append(f"\u2022 {reason} ({sign}{weight:.0f})")

    if breakdown_lines:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(breakdown_lines),
            }
        })

    # Velocity callout
    if alert.velocity_applied and alert.velocity_multiplier > 1.0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"\u26a1 *Velocity bonus active* — signals accumulating rapidly (x{alert.velocity_multiplier:.2f} multiplier)",
            }
        })

    # Tribal pattern callout
    if alert.tribal_pattern_text:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"\u26a1 *Tribal match: {alert.tribal_pattern_text}*\n"
                    f"This profile matches a pattern that converted at a higher rate than average."
                ),
            }
        })

    blocks.append({"type": "divider"})

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "\u2713 Looks right", "emoji": True},
                "style": "primary",
                "action_id": "alert_looks_right",
                "value": alert.alert_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "\u2717 Disagree \u2014 give feedback", "emoji": True},
                "style": "danger",
                "action_id": "alert_disagree",
                "value": alert.alert_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "\u2192 View in Salesforce", "emoji": True},
                "action_id": "alert_view_sf",
                "value": alert.account_id,
            },
        ]
    })

    return blocks


def format_realtime_text(alert: Alert) -> str:
    """Plain-text fallback for a CRITICAL or HIGH alert (console mode)."""
    emoji = TIER_EMOJI.get(alert.alert_tier, "")
    lines = [
        f"{emoji} {alert.alert_tier} — {_alert_type_label(alert.alert_type)}",
        f"{alert.account_name}",
        f"Score: {alert.score_at_fire:.0f} — here's why:",
    ]

    for contrib in alert.score_breakdown_snapshot[:5]:
        weight = contrib.get("decayed_weight", 0)
        reason = contrib.get("reason_text", contrib.get("signal_type", ""))
        sign = "+" if weight >= 0 else ""
        lines.append(f"  \u2022 {reason} ({sign}{weight:.0f})")

    if alert.velocity_applied and alert.velocity_multiplier > 1.0:
        lines.append(f"\n\u26a1 Velocity bonus active (x{alert.velocity_multiplier:.2f} multiplier)")

    if alert.tribal_pattern_text:
        lines.append(f"\n\u26a1 Tribal match: {alert.tribal_pattern_text}")
        lines.append("This profile matches a pattern that converted at a higher rate than average.")

    lines.append(f"\n[View in Salesforce: {SF_BASE_URL}/{alert.account_id}]")

    return "\n".join(lines)


def format_digest_blocks(alert: Alert) -> list[dict]:
    """
    Format a STANDARD morning digest alert as Slack Block Kit blocks.
    The alert's score_breakdown_snapshot contains per-account summaries.
    """
    blocks = []

    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"\U0001f4cb Morning Digest — Your Top Accounts",
            "emoji": True,
        }
    })

    # Each account in the digest
    for rank, acct_summary in enumerate(alert.score_breakdown_snapshot, 1):
        acct_name = acct_summary.get("account_name", acct_summary.get("account_id", ""))
        score = acct_summary.get("final_score", 0)
        top_signals = acct_summary.get("top_signals", [])
        velocity = acct_summary.get("velocity_applied", False)
        tribal = acct_summary.get("tribal_pattern_text")

        # Top signal reason
        top_reason = ""
        if top_signals:
            top_reason = top_signals[0].get("reason_text", top_signals[0].get("signal_type", ""))

        line = f"*{rank}. {acct_name}* — Score {score:.0f}"
        if top_reason:
            line += f"\n      _{top_reason}_"
        if velocity:
            line += " \u26a1"
        if tribal:
            line += f" \u2022 Tribal: {tribal}"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": line},
        })

    blocks.append({"type": "divider"})

    return blocks


def format_digest_text(alert: Alert) -> str:
    """Plain-text fallback for a morning digest (console mode)."""
    lines = ["\U0001f4cb Morning Digest — Your Top Accounts", ""]

    for rank, acct_summary in enumerate(alert.score_breakdown_snapshot, 1):
        acct_name = acct_summary.get("account_name", acct_summary.get("account_id", ""))
        score = acct_summary.get("final_score", 0)
        top_signals = acct_summary.get("top_signals", [])

        top_reason = ""
        if top_signals:
            top_reason = top_signals[0].get("reason_text", top_signals[0].get("signal_type", ""))

        lines.append(f"  {rank}. {acct_name} — Score {score:.0f} — {top_reason}")

    return "\n".join(lines)


def _alert_type_label(alert_type: str) -> str:
    """Human-readable label for alert types."""
    labels = {
        "high_score_active": "High-score signal on active account",
        "reengagement_window": "Re-engagement window detected",
        "untouched_high_score": "Untouched high-score account",
        "morning_digest": "Morning Digest",
    }
    return labels.get(alert_type, alert_type)
