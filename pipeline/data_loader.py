"""
Data loader — reads synthetic data files from data/synthetic/.

In DEMO_MODE, all adapters go through this module.
In production (future), adapters will call external APIs instead.

Usage:
    loader = DataLoader()
    events = loader.get_signal_events()
    accounts = loader.get_accounts()
    reps = loader.get_reps()
"""

import csv
import json
import os
from pathlib import Path


_SYNTHETIC_DIR = Path(__file__).parent.parent / "data" / "synthetic"


class DataLoader:
    """Loads and caches synthetic data files from data/synthetic/."""

    def __init__(self, data_dir: Path | None = None):
        self._dir = data_dir or _SYNTHETIC_DIR
        self._cache: dict = {}

    # ── JSON loaders ─────────────────────────────────────────────────────────

    def get_signal_events(self) -> list[dict]:
        """All signal events (~5987 records)."""
        return self._load_json("signal_events.json")

    def get_score_history(self) -> list[dict]:
        """Weekly score snapshots (~3017 records)."""
        return self._load_json("score_history.json")

    def get_tribal_patterns(self) -> list[dict]:
        """Tribal pattern definitions (7 patterns)."""
        return self._load_json("tribal_patterns.json")

    def get_account_preferences(self) -> list[dict]:
        """Per-rep, per-account snooze/override records (25 records)."""
        return self._load_json("account_preferences.json")

    def get_alert_log(self) -> list[dict]:
        """Pre-generated alert log (~1394 alerts)."""
        return self._load_json("alert_log.json")

    def get_reps(self) -> list[dict]:
        """Rep roster (19 reps — SDRs, AEs, managers)."""
        return self._load_json("reps.json")

    # ── CSV loaders ──────────────────────────────────────────────────────────

    def get_accounts(self) -> list[dict]:
        """Salesforce accounts (500 records across 3 tiers)."""
        return self._load_csv("sf_accounts.csv")

    def get_contacts(self) -> list[dict]:
        """Salesforce contacts (~247 records)."""
        return self._load_csv("sf_contacts.csv")

    def get_opportunities(self) -> list[dict]:
        """Salesforce opportunities (~208 records)."""
        return self._load_csv("sf_opportunities.csv")

    # ── Convenience accessors ────────────────────────────────────────────────

    def get_account_map(self) -> dict[str, dict]:
        """Returns accounts keyed by Id for fast lookup."""
        return {a["Id"]: a for a in self.get_accounts()}

    def get_signal_events_by_type(self, signal_type: str) -> list[dict]:
        """Filter signal events to a specific signal_type."""
        return [e for e in self.get_signal_events() if e["signal_type"] == signal_type]

    def get_signal_events_by_types(self, signal_types: list[str]) -> list[dict]:
        """Filter signal events to a set of signal_types."""
        type_set = set(signal_types)
        return [e for e in self.get_signal_events() if e["signal_type"] in type_set]

    # ── Internal ─────────────────────────────────────────────────────────────

    def _load_json(self, filename: str) -> list[dict]:
        if filename not in self._cache:
            path = self._dir / filename
            with open(path, "r", encoding="utf-8") as f:
                self._cache[filename] = json.load(f)
        return self._cache[filename]

    def _load_csv(self, filename: str) -> list[dict]:
        if filename not in self._cache:
            path = self._dir / filename
            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                self._cache[filename] = list(reader)
        return self._cache[filename]
