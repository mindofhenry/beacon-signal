"""
Intent Surge adapter — detects spikes in category or competitor research.

Production source: Bombora, 6sense, or G2 intent data.
Demo mode: reads from data/mock_signals.json
"""

from .base import BaseAdapter, SignalEvent


class IntentSurgeAdapter(BaseAdapter):

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live intent integration not built")

    def get_signal_types(self) -> list[str]:
        return ["category_research", "competitor_research"]

    def _load_mock_signals(self, account_ids: list[str] | None) -> list[SignalEvent]:
        return []
