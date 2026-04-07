"""
FastMCP server — exposes Signal tools to Claude Desktop.

Tools:
1. get_prioritized_accounts — ranked account list with explanations
2. get_account_signals — all active signals for an account
3. get_score_breakdown — full weighted score components
4. configure_weights — adjust signal weights within org bounds
5. get_signal_decay — decay projections for account signals

Built in Phase 3. SSE transport for Railway, stdio for Claude Desktop.
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.adapters.job_change import JobChangeAdapter
from pipeline.adapters.intent_surge import IntentSurgeAdapter
from pipeline.adapters.engagement import EngagementAdapter
from pipeline.adapters.funding_growth import FundingGrowthAdapter
from pipeline.config import load_weights_config
from pipeline.data_loader import DataLoader
from pipeline.decay import exponential_decay, get_decayed_weight
from pipeline.explainer import template_explanation, llm_explanation, batch_explanations
from pipeline.scorer import ScoringEngine, AccountScore

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

mcp = FastMCP("beacon-signal")

# Demo mode "today" — matches beacon-data's DEMO_TODAY
DEMO_AS_OF = datetime(2026, 3, 31, tzinfo=timezone.utc)

# Signal type → category mapping (for half-life lookups)
_TYPE_TO_CATEGORY = {
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

# beacon-data type → Signal type mapping (for tribal pattern matching)
_BEACON_TO_SIGNAL = {
    "job_change": "champion_hired",
    "executive_change": "economic_buyer_change",
    "intent_surge": "category_research",
    "competitor_mention": "competitor_research",
    "pricing_page_visit": "pricing_page_visit",
    "content_download": "content_download",
    "case_study_view": "case_study_view",
    "web_visit": "web_visit",
    "funding_event": "new_funding_round",
    "technology_install": "technology_install",
}


# ---------------------------------------------------------------------------
# Startup state — loaded once, reused across tool calls
# ---------------------------------------------------------------------------

class _State:
    """Server-wide state initialized at startup."""

    def __init__(self):
        self.config = load_weights_config()
        self.loader = DataLoader()
        self.engine = ScoringEngine(self.config)

        # Load all signals via adapters
        adapters = [
            JobChangeAdapter(self.config),
            IntentSurgeAdapter(self.config),
            EngagementAdapter(self.config),
            FundingGrowthAdapter(self.config),
        ]
        self.all_signals = []
        for adapter in adapters:
            self.all_signals.extend(adapter.fetch_signals())

        # Group signals by account
        self.signals_by_account: dict[str, list] = defaultdict(list)
        for s in self.all_signals:
            self.signals_by_account[s.account_id].append(s)

        # Score all accounts
        self.scores = self.engine.score_accounts(self.all_signals, as_of=DEMO_AS_OF)

        # Apply tribal pattern matching
        patterns = self.loader.get_tribal_patterns()
        account_map = self.loader.get_account_map()
        for score in self.scores:
            pid, pname = _check_tribal_patterns(
                score.account_id,
                self.signals_by_account.get(score.account_id, []),
                patterns,
                account_map,
            )
            if pid:
                score.tribal_pattern_id = pid
                score.tribal_pattern_text = pname

        # Build lookup maps
        self.score_map: dict[str, AccountScore] = {s.account_id: s for s in self.scores}
        self.account_map = account_map
        self.preferences = self.loader.get_account_preferences()

        # Build rep → accounts map via opportunities
        self.rep_accounts: dict[str, set[str]] = defaultdict(set)
        for opp in self.loader.get_opportunities():
            owner = opp.get("OwnerId", "")
            acct = opp.get("AccountId", "")
            if owner and acct:
                self.rep_accounts[owner].add(acct)

    def get_snoozed_accounts(self) -> set[str]:
        """Return account IDs currently snoozed (not expired as of DEMO_AS_OF)."""
        snoozed = set()
        for pref in self.preferences:
            if pref["preference_type"] != "snooze":
                continue
            expires = pref.get("expires_date", "")
            if expires:
                exp_date = datetime.fromisoformat(expires).replace(tzinfo=timezone.utc)
                if exp_date < DEMO_AS_OF:
                    continue  # Expired
            snoozed.add(pref["account_id"])
        return snoozed

    def rescore(self):
        """Re-run scoring with current config (after weight changes)."""
        self.engine = ScoringEngine(self.config)
        self.scores = self.engine.score_accounts(self.all_signals, as_of=DEMO_AS_OF)

        patterns = self.loader.get_tribal_patterns()
        for score in self.scores:
            pid, pname = _check_tribal_patterns(
                score.account_id,
                self.signals_by_account.get(score.account_id, []),
                patterns,
                self.account_map,
            )
            if pid:
                score.tribal_pattern_id = pid
                score.tribal_pattern_text = pname

        self.score_map = {s.account_id: s for s in self.scores}


# Tribal pattern matching (adapted from run_scoring.py)
def _check_tribal_patterns(
    account_id: str,
    signals: list,
    patterns: list[dict],
    account_map: dict,
) -> tuple[str | None, str | None]:
    """Check if an account matches any tribal pattern."""
    by_type: dict[str, list] = defaultdict(list)
    for s in signals:
        by_type[s.signal_type].append(s)
    for lst in by_type.values():
        lst.sort(key=lambda s: s.triggered_at)

    account = account_map.get(account_id, {})

    for pattern in patterns:
        if pattern.get("status") not in ("confirmed", "monitoring"):
            continue
        conditions = pattern["signal_conditions"]

        if "signal_type_required" in conditions:
            required_beacon = conditions["signal_type_required"]
            required = _BEACON_TO_SIGNAL.get(required_beacon, required_beacon)
            if required not in by_type:
                continue

            if "followed_by" in conditions:
                followed_beacon = conditions["followed_by"]
                followed = _BEACON_TO_SIGNAL.get(followed_beacon, followed_beacon)
                window = conditions.get("within_days", 60)
                matched = False
                for req_sig in by_type[required]:
                    cutoff = req_sig.triggered_at + timedelta(days=window)
                    if any(
                        f.triggered_at >= req_sig.triggered_at and f.triggered_at <= cutoff
                        for f in by_type.get(followed, [])
                    ):
                        matched = True
                        break
                if not matched:
                    continue

            elif "funding_stage" in conditions:
                stage = account.get("FundingStage", "") or account.get("funding_stage", "")
                if conditions["funding_stage"] not in stage:
                    continue

            return pattern["id"], pattern["name"]

        elif "min_signals_in_week" in conditions:
            must_include = set(
                _BEACON_TO_SIGNAL.get(t, t) for t in conditions.get("must_include", [])
            )
            min_count = conditions["min_signals_in_week"]
            all_sorted = sorted(signals, key=lambda s: s.triggered_at)
            matched = False
            for i, sig in enumerate(all_sorted):
                window_end = sig.triggered_at + timedelta(days=7)
                window_sigs = [s for s in all_sorted[i:] if s.triggered_at <= window_end]
                if len(window_sigs) >= min_count:
                    types_in_window = {s.signal_type for s in window_sigs}
                    if must_include.issubset(types_in_window):
                        matched = True
                        break
            if not matched:
                continue
            return pattern["id"], pattern["name"]

    return None, None


# Initialize state at import time
_state = _State()


# ---------------------------------------------------------------------------
# Tool 1: get_prioritized_accounts
# ---------------------------------------------------------------------------

@mcp.tool()
def get_prioritized_accounts(
    rep_id: str | None = None,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    """
    Return a ranked list of accounts by signal score.

    Excludes snoozed accounts. Optionally filter to a rep's accounts.
    Each result includes score, top 3 signal contributions, velocity flag,
    tribal pattern match, and a plain-English explanation.

    Args:
        rep_id: Optional rep ID to filter accounts (e.g. 'ae_1', 'sdr_3').
        top_n: Number of accounts to return (default 10).
    """
    snoozed = _state.get_snoozed_accounts()

    # Filter scores
    filtered = []
    for score in _state.scores:
        if score.account_id in snoozed:
            continue
        if rep_id and score.account_id not in _state.rep_accounts.get(rep_id, set()):
            continue
        filtered.append(score)

    # Already sorted by final_score desc from scoring engine
    top_scores = filtered[:top_n]

    # Generate explanations in batch
    explanations = batch_explanations(top_scores, _state.account_map, as_of=DEMO_AS_OF)

    results = []
    for rank, score in enumerate(top_scores, 1):
        acct = _state.account_map.get(score.account_id, {})
        top_contribs = sorted(
            score.score_breakdown, key=lambda c: abs(c.decayed_weight), reverse=True
        )[:3]

        results.append({
            "rank": rank,
            "account_id": score.account_id,
            "account_name": acct.get("Name", score.account_id),
            "industry": acct.get("Industry", "Unknown"),
            "final_score": score.final_score,
            "top_signals": [
                {
                    "signal_type": c.signal_type,
                    "decayed_weight": round(c.decayed_weight, 1),
                    "reason_text": c.reason_text,
                }
                for c in top_contribs
            ],
            "velocity_active": score.velocity_applied,
            "velocity_multiplier": score.velocity_multiplier if score.velocity_applied else None,
            "tribal_pattern": score.tribal_pattern_text,
            "explanation": explanations.get(score.account_id, ""),
        })

    return results


# ---------------------------------------------------------------------------
# Tool 2: get_account_signals
# ---------------------------------------------------------------------------

@mcp.tool()
def get_account_signals(account_id: str) -> list[dict[str, Any]]:
    """
    Return all active signals for an account, sorted by most recent first.

    Each signal includes type, weight, reason, timestamp, and current decay factor.

    Args:
        account_id: The account ID (e.g. 'sf_acc_001').
    """
    signals = _state.signals_by_account.get(account_id, [])
    if not signals:
        return []

    time_decay_config = _state.config.get("time_decay", {})

    results = []
    for s in sorted(signals, key=lambda x: x.triggered_at, reverse=True):
        category = _TYPE_TO_CATEGORY.get(s.signal_type, "")
        half_life = time_decay_config.get(category, 30)
        age_days = (DEMO_AS_OF - s.triggered_at).total_seconds() / 86400
        decay_factor = exponential_decay(age_days, half_life)

        results.append({
            "signal_type": s.signal_type,
            "weight_applied": s.weight_applied,
            "reason_text": s.reason_text,
            "triggered_at": s.triggered_at.isoformat(),
            "decay_factor": round(decay_factor, 4),
            "decayed_weight": round(s.weight_applied * decay_factor, 2),
            "age_days": round(age_days, 1),
        })

    return results


# ---------------------------------------------------------------------------
# Tool 3: get_score_breakdown
# ---------------------------------------------------------------------------

@mcp.tool()
def get_score_breakdown(account_id: str) -> dict[str, Any]:
    """
    Return the full weighted score breakdown for an account.

    Shows every signal contribution with raw weight, decay factor, decayed weight,
    and reason. Includes velocity status, tribal pattern, and explanation.

    Args:
        account_id: The account ID (e.g. 'sf_acc_001').
    """
    score = _state.score_map.get(account_id)
    if not score:
        return {"error": f"No score found for account {account_id}"}

    acct = _state.account_map.get(account_id, {})
    account_name = acct.get("Name", account_id)
    industry = acct.get("Industry", "Unknown")

    # Generate explanation
    explanation = llm_explanation(score, account_name, industry, as_of=DEMO_AS_OF)

    contributions = []
    for c in sorted(score.score_breakdown, key=lambda x: abs(x.decayed_weight), reverse=True):
        contributions.append({
            "signal_type": c.signal_type,
            "raw_weight": c.raw_weight,
            "decay_factor": round(c.decay_factor, 4),
            "decayed_weight": round(c.decayed_weight, 2),
            "reason_text": c.reason_text,
            "triggered_at": c.triggered_at.isoformat(),
        })

    return {
        "account_id": account_id,
        "account_name": account_name,
        "industry": industry,
        "final_score": score.final_score,
        "signal_count": len(score.score_breakdown),
        "contributions": contributions,
        "velocity_active": score.velocity_applied,
        "velocity_multiplier": score.velocity_multiplier if score.velocity_applied else None,
        "tribal_pattern_id": score.tribal_pattern_id,
        "tribal_pattern_text": score.tribal_pattern_text,
        "explanation": explanation,
        "calculated_at": score.calculated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Tool 4: configure_weights
# ---------------------------------------------------------------------------

@mcp.tool()
def configure_weights(signal_type: str, new_weight: float) -> dict[str, Any]:
    """
    Adjust the weight for a signal type within org-level bounds.

    Changes are in-memory only for this session — does not write back to YAML.
    After changing, scores are recalculated automatically.

    Args:
        signal_type: The signal subtype to adjust (e.g. 'champion_hired', 'pricing_page_visit').
        new_weight: The new weight value. Must be within org bounds (0-50).
    """
    bounds = _state.config.get("bounds", {})
    min_w = bounds.get("min_weight", 0)
    max_w = bounds.get("max_weight", 50)

    if new_weight < min_w or new_weight > max_w:
        return {
            "error": f"Weight {new_weight} is outside org bounds [{min_w}, {max_w}]",
            "min_weight": min_w,
            "max_weight": max_w,
        }

    # Find current weight
    old_weight = None
    signal_weights = _state.config.get("signal_weights", {})
    for category, subtypes in signal_weights.items():
        if isinstance(subtypes, dict) and signal_type in subtypes:
            old_weight = subtypes[signal_type]
            subtypes[signal_type] = new_weight
            break

    if old_weight is None:
        return {"error": f"Unknown signal type: {signal_type}"}

    # Re-score with updated weights
    _state.rescore()

    return {
        "signal_type": signal_type,
        "old_weight": old_weight,
        "new_weight": new_weight,
        "status": "updated",
        "note": "Scores recalculated. Change is in-memory only (session scope).",
    }


# ---------------------------------------------------------------------------
# Tool 5: get_signal_decay
# ---------------------------------------------------------------------------

@mcp.tool()
def get_signal_decay(
    account_id: str,
    signal_type: str | None = None,
) -> list[dict[str, Any]]:
    """
    Show decay projections for signals on an account.

    For each signal, shows current decayed weight and projections at +7d, +14d, +30d.

    Args:
        account_id: The account ID (e.g. 'sf_acc_001').
        signal_type: Optional filter to a specific signal type.
    """
    signals = _state.signals_by_account.get(account_id, [])
    if not signals:
        return []

    if signal_type:
        signals = [s for s in signals if s.signal_type == signal_type]

    time_decay_config = _state.config.get("time_decay", {})

    results = []
    for s in sorted(signals, key=lambda x: x.triggered_at, reverse=True):
        category = _TYPE_TO_CATEGORY.get(s.signal_type, "")
        half_life = time_decay_config.get(category, 30)
        age_days = (DEMO_AS_OF - s.triggered_at).total_seconds() / 86400

        current_factor = exponential_decay(age_days, half_life)
        factor_7d = exponential_decay(age_days + 7, half_life)
        factor_14d = exponential_decay(age_days + 14, half_life)
        factor_30d = exponential_decay(age_days + 30, half_life)

        results.append({
            "signal_type": s.signal_type,
            "reason_text": s.reason_text,
            "triggered_at": s.triggered_at.isoformat(),
            "raw_weight": s.weight_applied,
            "half_life_days": half_life,
            "age_days": round(age_days, 1),
            "current": {
                "decay_factor": round(current_factor, 4),
                "decayed_weight": round(s.weight_applied * current_factor, 2),
            },
            "projected_7d": {
                "decay_factor": round(factor_7d, 4),
                "decayed_weight": round(s.weight_applied * factor_7d, 2),
            },
            "projected_14d": {
                "decay_factor": round(factor_14d, 4),
                "decayed_weight": round(s.weight_applied * factor_14d, 2),
            },
            "projected_30d": {
                "decay_factor": round(factor_30d, 4),
                "decayed_weight": round(s.weight_applied * factor_30d, 2),
            },
        })

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if os.environ.get("PORT"):
        mcp.run(transport="sse", host="0.0.0.0", port=int(os.environ["PORT"]))
    else:
        mcp.run(transport="stdio")
