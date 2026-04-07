"""
Funding/Growth adapter — detects new funding rounds and technology installs.

beacon-data signal types consumed:
  - funding_event      → new_funding_round
  - technology_install → technology_install

Production source: Crunchbase, PitchBook, or BuiltWith.
Demo mode: reads from data/synthetic/signal_events.json via DataLoader.
"""

from datetime import datetime, timezone

from pipeline.data_loader import DataLoader
from .base import BaseAdapter, SignalEvent

_BEACON_TYPES = ["funding_event", "technology_install"]

_TYPE_MAP = {
    "funding_event": "new_funding_round",
    "technology_install": "technology_install",
}


class FundingGrowthAdapter(BaseAdapter):

    def __init__(self, config: dict, demo_mode: bool = True):
        super().__init__(config, demo_mode)
        self._loader = DataLoader()

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live funding integration not built")

    def get_signal_types(self) -> list[str]:
        return ["new_funding_round", "headcount_growth", "technology_install"]

    def _load_mock_signals(self, account_ids: list[str] | None) -> list[SignalEvent]:
        raw = self._loader.get_signal_events_by_types(_BEACON_TYPES)
        if account_ids is not None:
            id_set = set(account_ids)
            raw = [e for e in raw if e["account_id"] in id_set]

        events = []
        for r in raw:
            signal_type = _TYPE_MAP[r["signal_type"]]
            weight = self._get_weight(signal_type)
            events.append(SignalEvent(
                account_id=r["account_id"],
                signal_type=signal_type,
                signal_value={"source": r["source"], **r.get("metadata", {})},
                weight_applied=weight,
                reason_text=r["reason_text"],
                triggered_at=_parse_date(r["signal_date"]),
            ))
        return events


def _parse_date(date_str: str) -> datetime:
    d = datetime.fromisoformat(date_str)
    return d.replace(tzinfo=timezone.utc)
