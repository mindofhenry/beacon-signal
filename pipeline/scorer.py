"""
Weighted Scoring Engine

Takes signal events from all adapters, applies:
1. Configured weights (from weights.yaml)
2. Time decay (signals lose weight over time, configurable half-life)
3. Velocity bonus (accounts accumulating signals faster get a boost)
4. Account-level aggregation (signals from multiple contacts roll up)

Outputs a scored + ranked account list with full breakdown.

Key principle: score_breakdown is written at scoring time, not generated
after the fact. Every score is explainable because the breakdown IS the score.
"""

import math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pipeline.adapters.base import SignalEvent


@dataclass
class SignalContribution:
    """One signal's contribution to an account score."""
    signal_type: str
    signal_value: dict
    raw_weight: float
    decayed_weight: float
    reason_text: str
    triggered_at: datetime
    decay_factor: float


@dataclass
class AccountScore:
    """Final scored output for one account."""
    account_id: str
    final_score: float
    score_breakdown: list[SignalContribution]
    velocity_applied: bool
    velocity_multiplier: float
    tribal_pattern_id: str | None = None
    tribal_pattern_text: str | None = None
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ScoringEngine:
    """Stateless scoring engine. Give it signals + config, get back ranked accounts."""

    def __init__(self, config: dict):
        self.config = config
        self.time_decay_config = config.get("time_decay", {})
        self.velocity_config = config.get("velocity", {})

    def score_accounts(
        self,
        signals: list[SignalEvent],
        as_of: datetime | None = None,
    ) -> list[AccountScore]:
        """
        Score all accounts from a list of signal events.
        Returns list of AccountScore objects, sorted by final_score descending.
        """
        if as_of is None:
            as_of = datetime.now(timezone.utc)

        # Group signals by account
        account_signals: dict[str, list[SignalEvent]] = {}
        for signal in signals:
            account_signals.setdefault(signal.account_id, []).append(signal)

        # Score each account
        scores = []
        for account_id, acct_signals in account_signals.items():
            score = self._score_single_account(account_id, acct_signals, as_of)
            scores.append(score)

        scores.sort(key=lambda s: s.final_score, reverse=True)
        return scores

    def _score_single_account(
        self,
        account_id: str,
        signals: list[SignalEvent],
        as_of: datetime,
    ) -> AccountScore:
        """Score one account from its signals."""
        contributions = []
        for signal in signals:
            decay_factor = self._calculate_decay(signal.signal_type, signal.triggered_at, as_of)
            decayed_weight = signal.weight_applied * decay_factor

            contributions.append(SignalContribution(
                signal_type=signal.signal_type,
                signal_value=signal.signal_value,
                raw_weight=signal.weight_applied,
                decayed_weight=decayed_weight,
                reason_text=signal.reason_text,
                triggered_at=signal.triggered_at,
                decay_factor=decay_factor,
            ))

        base_score = sum(c.decayed_weight for c in contributions)

        velocity_applied, velocity_multiplier = self._check_velocity(signals, as_of)
        final_score = base_score * velocity_multiplier if velocity_applied else base_score

        # Clamp to 0-100
        final_score = max(0.0, min(100.0, final_score))

        return AccountScore(
            account_id=account_id,
            final_score=round(final_score, 1),
            score_breakdown=contributions,
            velocity_applied=velocity_applied,
            velocity_multiplier=velocity_multiplier,
        )

    def _calculate_decay(
        self,
        signal_type: str,
        triggered_at: datetime,
        as_of: datetime,
    ) -> float:
        """
        Exponential decay: decay_factor = 0.5 ^ (age_in_days / half_life_days)
        """
        half_life_days = self._get_half_life(signal_type)
        if half_life_days <= 0:
            return 1.0

        age_days = (as_of - triggered_at).total_seconds() / 86400
        if age_days < 0:
            age_days = 0

        return round(math.pow(0.5, age_days / half_life_days), 4)

    def _get_half_life(self, signal_type: str) -> float:
        """Map signal subtypes to their parent category's half-life."""
        type_to_category = {
            "champion_hired": "job_change",
            "economic_buyer_change": "job_change",
            "champion_departed": "job_change",
            "category_research": "intent_surge",
            "competitor_research": "intent_surge",
            "pricing_page_visit": "engagement",
            "demo_request": "engagement",
            "content_download": "engagement",
            "case_study_view": "engagement",
            "web_visit": "engagement",
            "new_funding_round": "funding_growth",
            "headcount_growth": "funding_growth",
            "technology_install": "funding_growth",
            "last_activity_recent": "crm_activity",
            "open_opportunity": "crm_activity",
            "sequence_enrolled": "crm_activity",
        }
        category = type_to_category.get(signal_type, "")
        return self.time_decay_config.get(category, 30)

    def _check_velocity(
        self,
        signals: list[SignalEvent],
        as_of: datetime,
    ) -> tuple[bool, float]:
        """Check if signals are accumulating fast enough for velocity bonus."""
        window_days = self.velocity_config.get("window_days", 14)
        min_signals = self.velocity_config.get("min_signals", 3)
        bonus = self.velocity_config.get("bonus_multiplier", 1.25)

        recent_count = sum(
            1 for s in signals
            if (as_of - s.triggered_at).total_seconds() / 86400 <= window_days
        )

        if recent_count >= min_signals:
            return True, bonus
        return False, 1.0
