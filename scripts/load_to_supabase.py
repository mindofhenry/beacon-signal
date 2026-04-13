"""
Load beacon-data synthetic files into Supabase signal schema tables.

Reads from data/synthetic/ and inserts into:
  signal.tribal_patterns
  signal.score_history
  signal.signal_events
  signal.account_preferences
  signal.alert_log

Insert order matters — tribal_patterns first (score_history FK),
score_history second (signal_events FK).

Usage:
    python scripts/load_to_supabase.py
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BATCH_SIZE = 500
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic"

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY) must be set in .env")
    sys.exit(1)

sb = create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_timestamptz(date_str: str) -> str:
    """Convert a date string (YYYY-MM-DD or ISO) to timestamptz format."""
    if not date_str:
        return None
    if "T" in date_str:
        # Already has time component — ensure timezone
        if "+" not in date_str and "Z" not in date_str:
            return date_str + "+00:00"
        return date_str
    return date_str + "T00:00:00+00:00"


def batch_insert(table: str, rows: list[dict], schema: str = "signal") -> tuple[int, str | None]:
    """Insert rows in batches. Returns (inserted_count, first_error_or_None)."""
    inserted = 0
    first_error = None
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        try:
            result = sb.schema(schema).table(table).insert(batch).execute()
            inserted += len(result.data) if result.data else len(batch)
        except Exception as e:
            if first_error is None:
                first_error = str(e)[:300]
            # Try inserting remaining batches
            continue
    return inserted, first_error


def parse_score_from_title(title: str) -> float:
    """Extract the final score from alert title like 'Score spike: Acme (0 → 59)'."""
    match = re.search(r"→\s*(\d+)", title)
    if match:
        return float(match.group(1))
    # Fallback: try to find any number after arrow variants
    match = re.search(r"(\d+)\)?$", title)
    if match:
        return float(match.group(1))
    return 0.0


# ---------------------------------------------------------------------------
# Transform functions
# ---------------------------------------------------------------------------

def transform_tribal_patterns(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        rows.append({
            "id": r["id"],
            "pattern_name": r["name"],
            "pattern_description": f"Status: {r.get('status', 'unknown')}, Confidence: {r.get('confidence', 'unknown')}",
            "signal_conditions": r["signal_conditions"],
            "historical_conversion_rate": r["historical_conversion_rate"],
            "sample_size": r["sample_size"],
            "created_at": to_timestamptz(r["discovered_date"]),
        })
    return rows


def transform_score_history(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        rows.append({
            "id": r["id"],
            "account_id": r["account_id"],
            "final_score": r["score"],
            "score_breakdown": r["breakdown"],
            "tribal_pattern_id": r.get("tribal_pattern_id"),
            "rep_feedback": r.get("rep_feedback"),
            "calculated_at": to_timestamptz(r["score_date"]),
        })
    return rows


def transform_signal_events(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        rows.append({
            "id": r["id"],
            "account_id": r["account_id"],
            "signal_type": r["signal_type"],
            "signal_value": r.get("metadata", {}),
            "weight_applied": r["weight_applied"],
            "reason_text": r["reason_text"],
            "triggered_at": to_timestamptz(r["signal_date"]),
        })
    return rows


def transform_account_preferences(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        pref_type = r.get("preference_type", "")
        row = {
            "rep_id": r["rep_id"],
            "account_id": r["account_id"],
            "snoozed_until": to_timestamptz(r.get("expires_date")),
            "override_reason": r.get("reason"),
            "created_at": to_timestamptz(r.get("created_date")),
            "updated_at": to_timestamptz(r.get("created_date")),
        }
        if pref_type == "score_override":
            row["priority_override"] = 100
        rows.append(row)
    return rows


def transform_alert_log(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        fired_at = to_timestamptz(r["timestamp"])
        # Calculate acknowledged_at from response_time_hours
        acknowledged_at = None
        if r.get("responded") and r.get("response_time_hours"):
            fired_dt = datetime.fromisoformat(fired_at)
            acknowledged_at = (
                fired_dt + timedelta(hours=r["response_time_hours"])
            ).isoformat()

        # Determine channel from tier
        tier = r["tier"]
        channel = "digest" if tier == "STANDARD" else "slack_dm"

        # Parse score from title
        score = parse_score_from_title(r.get("title", ""))

        rows.append({
            "id": r["id"],
            "account_id": r["account_id"],
            "rep_id": r["rep_id"],
            "alert_tier": tier,
            "alert_type": r["alert_type"],
            "score_at_fire": score,
            "score_breakdown_snapshot": {"summary": r.get("body", "")},
            "fired_at": fired_at,
            "acknowledged_at": acknowledged_at,
            "channel": channel,
            "feedback": r.get("response_action"),
        })
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Beacon Signal — Supabase Loader")
    print("=" * 60)
    print(f"Data dir: {DATA_DIR}")
    print(f"Supabase: {SUPABASE_URL}")
    print()

    # --- 1. tribal_patterns (no FK deps) ---
    print("[1/5] Loading tribal_patterns...")
    raw = load_json("tribal_patterns.json")
    rows = transform_tribal_patterns(raw)
    count, err = batch_insert("tribal_patterns", rows)
    print(f"  ->{count}/{len(rows)} rows inserted")
    if err:
        print(f"  WARNING First error: {err}")

    # --- 2. score_history (FK → tribal_patterns) ---
    print("[2/5] Loading score_history...")
    raw = load_json("score_history.json")
    rows = transform_score_history(raw)
    count, err = batch_insert("score_history", rows)
    print(f"  ->{count}/{len(rows)} rows inserted")
    if err:
        print(f"  WARNING First error: {err}")

    # --- 3. signal_events (FK → score_history via contributed_to_score_id) ---
    print("[3/5] Loading signal_events...")
    raw = load_json("signal_events.json")
    rows = transform_signal_events(raw)
    count, err = batch_insert("signal_events", rows)
    print(f"  ->{count}/{len(rows)} rows inserted")
    if err:
        print(f"  WARNING First error: {err}")

    # --- 4. account_preferences ---
    print("[4/5] Loading account_preferences...")
    raw = load_json("account_preferences.json")
    rows = transform_account_preferences(raw)
    count, err = batch_insert("account_preferences", rows)
    print(f"  ->{count}/{len(rows)} rows inserted")
    if err:
        print(f"  WARNING First error: {err}")

    # --- 5. alert_log ---
    print("[5/5] Loading alert_log...")
    raw = load_json("alert_log.json")
    rows = transform_alert_log(raw)
    count, err = batch_insert("alert_log", rows)
    print(f"  ->{count}/{len(rows)} rows inserted")
    if err:
        print(f"  WARNING First error: {err}")

    print()
    print("=" * 60)
    print("Done.")
    print("=" * 60)


if __name__ == "__main__":
    main()
