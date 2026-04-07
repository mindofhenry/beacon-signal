"""
Alert evaluation engine — checks scores against thresholds and decides
which alerts to fire. Does NOT deliver alerts — that's slack.py's job.

Built in Phase 4. Stubbed here for architecture.
"""

from dataclasses import dataclass
from datetime import datetime
from pipeline.scorer import AccountScore


@dataclass
class Alert:
    """One alert to be delivered."""
    account_id: str
    rep_id: str
    alert_tier: str
    alert_type: str
    score_at_fire: float
    score_breakdown_snapshot: list[dict]
    channel: str


class AlertEngine:
    """Evaluates scores against thresholds. Produces alerts."""

    def __init__(self, config: dict):
        self.config = config

    def evaluate(self, scores: list[AccountScore]) -> list[Alert]:
        """Built in Phase 4."""
        raise NotImplementedError("Alert evaluation built in Phase 4")
