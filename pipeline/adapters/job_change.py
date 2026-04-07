"""
Job Change adapter — detects champion hires and economic buyer changes.

beacon-data signal types consumed:
  - job_change       → champion_hired
  - executive_change → economic_buyer_change

Production source: LinkedIn Sales Navigator, ZoomInfo, or similar.
Demo mode: reads from data/synthetic/signal_events.json via DataLoader.
"""

from datetime import datetime, timezone

from pipeline.data_loader import DataLoader
from .base import BaseAdapter, SignalEvent

_BEACON_TYPES = ["job_change", "executive_change"]

_TYPE_MAP = {
    "job_change": "champion_hired",
    "executive_change": "economic_buyer_change",
}


class JobChangeAdapter(BaseAdapter):

    def __init__(self, config: dict, demo_mode: bool = True):
        super().__init__(config, demo_mode)
        self._loader = DataLoader()

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live job change integration not built")

    def get_signal_types(self) -> list[str]:
        return ["champion_hired", "economic_buyer_change"]

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
    """Parse YYYY-MM-DD string to UTC datetime."""
    d = datetime.fromisoformat(date_str)
    return d.replace(tzinfo=timezone.utc)
