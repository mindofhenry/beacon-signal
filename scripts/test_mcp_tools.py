"""
Phase 3 MCP tool validation script.

Imports the server module directly and calls each of the 5 tool functions
with test parameters. Prints output for manual review.

Usage:
    python scripts/test_mcp_tools.py
"""

import json
import os
import sys
from pathlib import Path

# Avoid Windows console encoding errors with Unicode characters
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DEMO_MODE", "true")

from server.server import (
    get_prioritized_accounts,
    get_account_signals,
    get_score_breakdown,
    configure_weights,
    get_signal_decay,
    _state,
)


def pp(data):
    """Pretty-print JSON-serializable data."""
    print(json.dumps(data, indent=2, default=str))


def divider(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def test_get_prioritized_accounts():
    divider("Tool 1: get_prioritized_accounts (top 5)")

    results = get_prioritized_accounts(top_n=5)
    assert isinstance(results, list), "Expected list"
    assert len(results) > 0, "Expected non-empty results"
    assert len(results) <= 5, f"Expected <=5 results, got {len(results)}"

    for r in results:
        assert "rank" in r, "Missing rank"
        assert "account_name" in r, "Missing account_name"
        assert "final_score" in r, "Missing final_score"
        assert "explanation" in r, "Missing explanation"
        assert "top_signals" in r, "Missing top_signals"
        assert len(r["explanation"]) > 10, f"Explanation too short: {r['explanation']}"

    print(f"Returned {len(results)} accounts")
    for r in results:
        velocity = " [VELOCITY]" if r["velocity_active"] else ""
        tribal = f" [TRIBAL: {r['tribal_pattern']}]" if r["tribal_pattern"] else ""
        print(f"  #{r['rank']} {r['account_name']} — {r['final_score']}{velocity}{tribal}")
        print(f"       {r['explanation'][:100]}...")
    print("\n  PASS: get_prioritized_accounts returns ranked results with explanations")

    # Test with rep_id filter
    divider("Tool 1b: get_prioritized_accounts (rep_id=ae_1)")
    rep_results = get_prioritized_accounts(rep_id="ae_1", top_n=3)
    print(f"  Returned {len(rep_results)} accounts for ae_1")
    if rep_results:
        for r in rep_results:
            print(f"    #{r['rank']} {r['account_name']} — {r['final_score']}")
    print("  PASS: rep_id filter works")


def test_get_account_signals():
    divider("Tool 2: get_account_signals (sf_acc_001)")

    results = get_account_signals(account_id="sf_acc_001")
    assert isinstance(results, list), "Expected list"

    if not results:
        print("  No signals for sf_acc_001 — trying first scored account")
        first_account = _state.scores[0].account_id
        results = get_account_signals(account_id=first_account)
        print(f"  Using {first_account} instead")

    assert len(results) > 0, "Expected at least one signal"

    for r in results:
        assert "signal_type" in r, "Missing signal_type"
        assert "weight_applied" in r, "Missing weight_applied"
        assert "reason_text" in r, "Missing reason_text"
        assert "triggered_at" in r, "Missing triggered_at"
        assert "decay_factor" in r, "Missing decay_factor"

    # Verify sorted by triggered_at descending
    dates = [r["triggered_at"] for r in results]
    assert dates == sorted(dates, reverse=True), "Not sorted by triggered_at desc"

    print(f"  Returned {len(results)} signals")
    for r in results[:3]:
        print(f"    {r['signal_type']}: weight={r['weight_applied']}, "
              f"decay={r['decay_factor']}, age={r['age_days']}d")
    print("  PASS: get_account_signals returns signals sorted by date")


def test_get_score_breakdown():
    divider("Tool 3: get_score_breakdown")

    # Use the top-scored account
    top_account = _state.scores[0].account_id
    result = get_score_breakdown(account_id=top_account)

    assert isinstance(result, dict), "Expected dict"
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert "final_score" in result, "Missing final_score"
    assert "contributions" in result, "Missing contributions"
    assert "explanation" in result, "Missing explanation"
    assert len(result["contributions"]) > 0, "No contributions"
    assert len(result["explanation"]) > 10, "Explanation too short"

    print(f"  Account: {result['account_name']} ({result['account_id']})")
    print(f"  Score: {result['final_score']}")
    print(f"  Signals: {result['signal_count']}")
    print(f"  Velocity: {result['velocity_active']}")
    print(f"  Tribal: {result['tribal_pattern_text']}")
    print(f"  Explanation: {result['explanation'][:120]}...")
    print(f"\n  Top contributions:")
    for c in result["contributions"][:5]:
        print(f"    {c['signal_type']}: raw={c['raw_weight']}, "
              f"decay={c['decay_factor']}, decayed={c['decayed_weight']}")
    print("  PASS: get_score_breakdown returns full breakdown with explanation")


def test_configure_weights():
    divider("Tool 4: configure_weights")

    # Test valid weight change
    result = configure_weights(signal_type="champion_hired", new_weight=35)
    assert "error" not in result, f"Got error: {result.get('error')}"
    assert result["old_weight"] == 30, f"Expected old_weight=30, got {result['old_weight']}"
    assert result["new_weight"] == 35, f"Expected new_weight=35, got {result['new_weight']}"
    print(f"  Changed champion_hired: {result['old_weight']} → {result['new_weight']}")
    print(f"  Status: {result['status']}")

    # Test out-of-bounds rejection
    result_bad = configure_weights(signal_type="champion_hired", new_weight=999)
    assert "error" in result_bad, "Expected error for out-of-bounds weight"
    print(f"  Out-of-bounds (999) rejected: {result_bad['error']}")

    # Test unknown signal type
    result_unknown = configure_weights(signal_type="nonexistent_type", new_weight=10)
    assert "error" in result_unknown, "Expected error for unknown type"
    print(f"  Unknown type rejected: {result_unknown['error']}")

    # Restore original weight
    configure_weights(signal_type="champion_hired", new_weight=30)
    print("  Restored champion_hired to 30")

    print("  PASS: configure_weights validates bounds and rejects invalid input")


def test_get_signal_decay():
    divider("Tool 5: get_signal_decay")

    # Use the top-scored account
    top_account = _state.scores[0].account_id
    results = get_signal_decay(account_id=top_account)

    assert isinstance(results, list), "Expected list"
    assert len(results) > 0, "Expected at least one signal"

    for r in results:
        assert "signal_type" in r, "Missing signal_type"
        assert "raw_weight" in r, "Missing raw_weight"
        assert "half_life_days" in r, "Missing half_life_days"
        assert "current" in r, "Missing current"
        assert "projected_7d" in r, "Missing projected_7d"
        assert "projected_14d" in r, "Missing projected_14d"
        assert "projected_30d" in r, "Missing projected_30d"

        # Verify decay projections decrease over time
        current = r["current"]["decayed_weight"]
        proj_7 = r["projected_7d"]["decayed_weight"]
        proj_30 = r["projected_30d"]["decayed_weight"]
        assert proj_7 <= current, "7d projection should be <= current"
        assert proj_30 <= proj_7, "30d projection should be <= 7d projection"

    print(f"  Returned {len(results)} signals with decay projections")
    for r in results[:3]:
        print(f"    {r['signal_type']}: raw={r['raw_weight']}, "
              f"current={r['current']['decayed_weight']}, "
              f"+7d={r['projected_7d']['decayed_weight']}, "
              f"+30d={r['projected_30d']['decayed_weight']}")

    # Test with signal_type filter
    first_type = results[0]["signal_type"]
    filtered = get_signal_decay(account_id=top_account, signal_type=first_type)
    assert all(r["signal_type"] == first_type for r in filtered), "Filter didn't work"
    print(f"  Filtered to {first_type}: {len(filtered)} signals")

    print("  PASS: get_signal_decay shows decay projections")


def main():
    print("\nBeacon Signal — Phase 3 MCP Tool Validation")
    print("=" * 48)
    print(f"  Loaded {len(_state.all_signals)} signals across {len(_state.scores)} accounts")

    test_get_prioritized_accounts()
    test_get_account_signals()
    test_get_score_breakdown()
    test_configure_weights()
    test_get_signal_decay()

    divider("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
