"""
Job Change adapter — detects champion hires, economic buyer changes,
and champion departures at target accounts.

Production source: LinkedIn Sales Navigator, ZoomInfo, or similar.
Demo mode: reads from data/mock_signals.json
"""

from .base import BaseAdapter, SignalEvent


class JobChangeAdapter(BaseAdapter):

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live job change integration not built")

    def get_signal_types(self) -> list[str]:
        return ["champion_hired", "economic_buyer_change", "champion_departed"]

    def _load_mock_signals(self, account_ids: list[str] | None) -> list[SignalEvent]:
        # Phase 2: load from data/mock_signals.json
        return []
