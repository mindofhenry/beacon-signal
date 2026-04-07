"""
Funding/Growth adapter — detects new funding rounds and headcount growth.

Production source: Crunchbase, PitchBook, or LinkedIn.
Demo mode: reads from data/mock_signals.json
"""

from .base import BaseAdapter, SignalEvent


class FundingGrowthAdapter(BaseAdapter):

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live funding integration not built")

    def get_signal_types(self) -> list[str]:
        return ["new_funding_round", "headcount_growth"]

    def _load_mock_signals(self, account_ids: list[str] | None) -> list[SignalEvent]:
        return []
