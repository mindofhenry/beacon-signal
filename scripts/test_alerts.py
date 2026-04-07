"""
Phase 4 alert validation script.

Validates:
1. Alert evaluation engine produces CRITICAL, HIGH, STANDARD alerts
2. Sample formatted alert for each tier (plain text, not Slack blocks)
3. Snoozed accounts are excluded
4. Max alerts per rep per day limit is respected
5. Score breakdown is present on every alert

Usage:
    python scripts/test_alerts.py
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

os.environ.setdefault("DEMO_MODE", "true")

from pipeline.adapters.job_change import JobChangeAdapter
from pipeline.adapters.intent_surge import IntentSurgeAdapter
from pipeline.adapters.engagement import EngagementAdapter
from pipeline.adapters.funding_growth import FundingGrowthAdapter
from pipeline.config import load_weights_config, load_alert_config
from pipeline.data_loader import DataLoader
from pipeline.scorer import ScoringEngine

from alerts.engine import AlertEngine, get_snoozed_accounts
from alerts.formatter import format_realtime_text, format_digest_text

DEMO_AS_OF = datetime(2026, 3, 31, tzinfo=timezone.utc)

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def record(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((name, status, detail))
    mark = "\u2713" if passed else "\u2717"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def main():
    print("\nBeacon Signal — Phase 4 Alert Validation")
    print("=" * 50)

    # --- Setup ---
    config = load_weights_config()
    alert_config = load_alert_config()
    loader = DataLoader()

    adapters = [
        JobChangeAdapter(config),
        IntentSurgeAdapter(config),
        EngagementAdapter(config),
        FundingGrowthAdapter(config),
    ]
    all_signals = []
    for adapter in adapters:
        all_signals.extend(adapter.fetch_signals())

    signals_by_account: dict[str, list] = defaultdict(list)
    for s in all_signals:
        signals_by_account[s.account_id].append(s)

    engine = ScoringEngine(config)
    scores = engine.score_accounts(all_signals, as_of=DEMO_AS_OF)
    account_map = loader.get_account_map()

    rep_accounts: dict[str, set[str]] = defaultdict(set)
    for opp in loader.get_opportunities():
        owner = opp.get("OwnerId", "")
        acct = opp.get("AccountId", "")
        if owner and acct:
            rep_accounts[owner].add(acct)

    preferences = loader.get_account_preferences()
    snoozed = get_snoozed_accounts(preferences, DEMO_AS_OF)

    print(f"\n  Accounts scored: {len(scores)}")
    print(f"  Snoozed accounts: {len(snoozed)} — {snoozed}")
    print(f"  Reps with accounts: {len(rep_accounts)}")
    print(f"  Signals loaded: {len(all_signals)}")

    # --- Test 1: Run evaluation ---
    print(f"\n--- Test 1: Alert evaluation ---")
    alert_engine = AlertEngine(alert_config)
    alerts = alert_engine.evaluate(
        scores=scores,
        signals_by_account=signals_by_account,
        rep_accounts=rep_accounts,
        account_map=account_map,
        snoozed_accounts=snoozed,
        as_of=DEMO_AS_OF,
    )

    critical = [a for a in alerts if a.alert_tier == "CRITICAL"]
    high = [a for a in alerts if a.alert_tier == "HIGH"]
    standard = [a for a in alerts if a.alert_tier == "STANDARD"]

    print(f"\n  Total alerts: {len(alerts)}")
    print(f"  CRITICAL: {len(critical)}")
    print(f"  HIGH: {len(high)}")
    print(f"  STANDARD (digests): {len(standard)}")

    record("Alerts generated", len(alerts) > 0, f"{len(alerts)} total")
    record("CRITICAL alerts exist", len(critical) > 0, f"{len(critical)} CRITICAL")
    record("HIGH alerts exist", len(high) > 0, f"{len(high)} HIGH")
    record("STANDARD digests exist", len(standard) > 0, f"{len(standard)} digests")

    # --- Test 2: Sample formatted alerts ---
    print(f"\n--- Test 2: Sample formatted alerts ---")

    if critical:
        sample = critical[0]
        print(f"\n  Sample CRITICAL alert:")
        text = format_realtime_text(sample)
        print(text)
        record("CRITICAL format has breakdown",
               len(sample.score_breakdown_snapshot) > 0,
               f"{len(sample.score_breakdown_snapshot)} contributions")
    else:
        record("CRITICAL format has breakdown", False, "No CRITICAL alerts to test")

    if high:
        sample = high[0]
        print(f"\n  Sample HIGH alert:")
        text = format_realtime_text(sample)
        print(text)
        record("HIGH format has breakdown",
               len(sample.score_breakdown_snapshot) > 0,
               f"{len(sample.score_breakdown_snapshot)} contributions")
    else:
        record("HIGH format has breakdown", False, "No HIGH alerts to test")

    if standard:
        sample = standard[0]
        print(f"\n  Sample STANDARD digest:")
        text = format_digest_text(sample)
        print(text)
        record("STANDARD digest has accounts",
               len(sample.score_breakdown_snapshot) > 0,
               f"{len(sample.score_breakdown_snapshot)} accounts in digest")
    else:
        record("STANDARD digest has accounts", False, "No STANDARD alerts to test")

    # --- Test 3: Every alert includes score breakdown ---
    print(f"\n--- Test 3: Score breakdown on every alert ---")
    realtime_alerts = critical + high
    if realtime_alerts:
        all_have_breakdown = all(len(a.score_breakdown_snapshot) > 0 for a in realtime_alerts)
        record("All real-time alerts have breakdown", all_have_breakdown,
               f"{sum(1 for a in realtime_alerts if len(a.score_breakdown_snapshot) > 0)}/{len(realtime_alerts)}")
    else:
        record("All real-time alerts have breakdown", False, "No real-time alerts")

    # --- Test 4: Snoozed accounts excluded ---
    print(f"\n--- Test 4: Snoozed accounts excluded ---")
    alerted_accounts = {a.account_id for a in alerts if a.account_id != "digest"}
    snoozed_in_alerts = alerted_accounts & snoozed
    record("No snoozed accounts in alerts", len(snoozed_in_alerts) == 0,
           f"snoozed in alerts: {snoozed_in_alerts}" if snoozed_in_alerts else "clean")

    # Also check digest contents
    digest_accounts = set()
    for a in standard:
        for acct_summary in a.score_breakdown_snapshot:
            digest_accounts.add(acct_summary.get("account_id", ""))
    snoozed_in_digest = digest_accounts & snoozed
    record("No snoozed accounts in digests", len(snoozed_in_digest) == 0,
           f"snoozed in digests: {snoozed_in_digest}" if snoozed_in_digest else "clean")

    # --- Test 5: Max alerts per rep per day ---
    print(f"\n--- Test 5: Max alerts per rep per day limit ---")
    max_limit = alert_config.get("settings", {}).get("max_realtime_alerts_per_rep_per_day", 3)
    rep_realtime_counts: dict[str, int] = defaultdict(int)
    for a in realtime_alerts:
        rep_realtime_counts[a.rep_id] += 1

    over_limit = {rep: count for rep, count in rep_realtime_counts.items() if count > max_limit}
    record(f"No rep exceeds {max_limit} real-time alerts/day",
           len(over_limit) == 0,
           f"over limit: {over_limit}" if over_limit else "all within limit")

    if rep_realtime_counts:
        max_rep = max(rep_realtime_counts, key=rep_realtime_counts.get)
        print(f"  Highest: {max_rep} with {rep_realtime_counts[max_rep]} alerts")

    # --- Test 6: Historical alert loading ---
    print(f"\n--- Test 6: Historical alert log loading ---")
    from alerts.engine import load_historical_alerts
    historical = load_historical_alerts(loader.get_alert_log())
    record("Historical alerts loaded", len(historical) > 0, f"{len(historical)} records")

    # --- Summary ---
    print(f"\n{'='*50}")
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = sum(1 for _, s, _ in results if s == FAIL)
    print(f"  Results: {passed} passed, {failed} failed out of {len(results)} tests")

    if failed:
        print(f"\n  Failed tests:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"    \u2717 {name}: {detail}")

    print(f"{'='*50}\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
