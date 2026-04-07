"""
Phase 2 end-to-end scoring script.

Loads all signal events via adapters, runs the scoring engine, and prints
the top 10 accounts with full score breakdowns. Validates:
  - Tribal pattern detection on at least one account
  - Velocity bonus showing on at least one account

Usage:
    python pipeline/run_scoring.py
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add repo root to path so imports work when running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DEMO_MODE", "true")

from pipeline.adapters.job_change import JobChangeAdapter
from pipeline.adapters.intent_surge import IntentSurgeAdapter
from pipeline.adapters.engagement import EngagementAdapter
from pipeline.adapters.funding_growth import FundingGrowthAdapter
from pipeline.config import load_weights_config
from pipeline.data_loader import DataLoader
from pipeline.scorer import ScoringEngine

# Demo mode "today" matches beacon-data's DEMO_TODAY = March 31, 2026
DEMO_AS_OF = datetime(2026, 3, 31, tzinfo=timezone.utc)

# Beacon-data signal types → Signal signal types (for pattern matching)
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


def load_all_signals(config: dict) -> list:
    """Fetch signals from all adapters."""
    adapters = [
        JobChangeAdapter(config),
        IntentSurgeAdapter(config),
        EngagementAdapter(config),
        FundingGrowthAdapter(config),
    ]
    all_signals = []
    for adapter in adapters:
        signals = adapter.fetch_signals()
        all_signals.extend(signals)
        print(f"  {adapter.__class__.__name__}: {len(signals)} signals loaded")
    return all_signals


def check_tribal_patterns(
    account_id: str,
    signals: list,
    patterns: list[dict],
    account_map: dict,
) -> tuple[str | None, str | None]:
    """
    Check if an account matches any tribal pattern.
    Returns (pattern_id, pattern_name) or (None, None).
    """
    # Index signals by type and sort by date
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

                # Check if any required signal is followed by the follow-up within window
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
                # tp_001: requires Series B in account data
                stage = account.get("FundingStage", "") or account.get("funding_stage", "")
                if conditions["funding_stage"] not in stage:
                    continue

            return pattern["id"], pattern["name"]

        elif "min_signals_in_week" in conditions:
            # tp_004: 4+ signals in any single week including required types
            must_include = set(
                _BEACON_TO_SIGNAL.get(t, t) for t in conditions.get("must_include", [])
            )
            min_count = conditions["min_signals_in_week"]

            # Check rolling 7-day windows
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


def print_score_report(
    scores: list,
    signals_by_account: dict,
    patterns: list[dict],
    account_map: dict,
    top_n: int = 10,
) -> None:
    """Print the top N accounts with full breakdown."""
    print(f"\n{'='*72}")
    print(f"  BEACON SIGNAL -- Top {top_n} Accounts  (as of {DEMO_AS_OF.date()})")
    print(f"{'='*72}")

    shown_tribal = False
    shown_velocity = False

    for rank, score in enumerate(scores[:top_n], 1):
        acct_id = score.account_id
        acct = account_map.get(acct_id, {})
        acct_name = acct.get("Name", acct_id)

        # Tribal pattern check
        pattern_id, pattern_name = check_tribal_patterns(
            acct_id,
            signals_by_account.get(acct_id, []),
            patterns,
            account_map,
        )
        if pattern_id:
            shown_tribal = True

        if score.velocity_applied:
            shown_velocity = True

        print(f"\n#{rank}  {acct_name} ({acct_id})")
        print(f"    Score: {score.final_score:.1f}", end="")
        if score.velocity_applied:
            print(f"  [VELOCITY x{score.velocity_multiplier}]", end="")
        if pattern_id:
            safe_name = pattern_name.encode("ascii", errors="replace").decode("ascii")
            print(f"  [PATTERN: {pattern_id} - {safe_name}]", end="")
        print()

        # Top 5 signal contributions
        top_contribs = sorted(
            score.score_breakdown, key=lambda c: c.decayed_weight, reverse=True
        )[:5]
        for c in top_contribs:
            print(
                f"    • {c.signal_type:<30} "
                f"raw={c.raw_weight:5.1f}  "
                f"decay={c.decay_factor:.3f}  "
                f"decayed={c.decayed_weight:5.1f}  "
                f"({c.triggered_at.date()})"
            )

    print(f"\n{'='*72}")
    print(f"  Total accounts scored: {len(scores)}")
    print(f"  Tribal pattern shown: {'yes' if shown_tribal else 'NO — none matched in top 10'}")
    print(f"  Velocity bonus shown: {'yes' if shown_velocity else 'NO — none in top 10'}")
    print(f"{'='*72}\n")

    if not shown_tribal:
        # Show first account with a tribal match anywhere in the list
        for score in scores:
            pid, pname = check_tribal_patterns(
                score.account_id,
                signals_by_account.get(score.account_id, []),
                patterns,
                account_map,
            )
            if pid:
                acct = account_map.get(score.account_id, {})
                print(f"  First tribal pattern match (rank #{scores.index(score)+1}):")
                safe_pname = pname.encode("ascii", errors="replace").decode("ascii")
                print(f"  {acct.get('Name', score.account_id)} - {pid}: {safe_pname}")
                print(f"  Score: {score.final_score:.1f}\n")
                break


def main():
    print("\nBeacon Signal — Phase 2 End-to-End Scoring")
    print("=" * 48)

    # Load config and data
    config = load_weights_config()
    loader = DataLoader()
    patterns = loader.get_tribal_patterns()
    account_map = loader.get_account_map()

    print(f"\nLoading signals from adapters...")
    all_signals = load_all_signals(config)
    print(f"  Total: {len(all_signals)} signals across {len(set(s.account_id for s in all_signals))} accounts")

    # Group for pattern matching and display
    signals_by_account: dict[str, list] = defaultdict(list)
    for s in all_signals:
        signals_by_account[s.account_id].append(s)

    # Run scoring engine
    print(f"\nRunning scoring engine (as of {DEMO_AS_OF.date()})...")
    engine = ScoringEngine(config)
    scores = engine.score_accounts(all_signals, as_of=DEMO_AS_OF)
    print(f"  Scored {len(scores)} accounts")

    velocity_count = sum(1 for s in scores if s.velocity_applied)
    print(f"  Accounts with velocity bonus: {velocity_count}")

    # Print report
    print_score_report(scores, signals_by_account, patterns, account_map)


if __name__ == "__main__":
    main()
