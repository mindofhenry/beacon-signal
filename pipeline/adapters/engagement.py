"""
Engagement adapter — tracks pricing page visits, demo requests,
and content downloads.

Production source: Marketo, HubSpot, website analytics.
Demo mode: reads from data/mock_signals.json
"""

from .base import BaseAdapter, SignalEvent


class EngagementAdapter(BaseAdapter):

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live engagement integration not built")

    def get_signal_types(self) -> list[str]:
        return ["pricing_page_visit", "demo_request", "content_download"]

    def _load_mock_signals(self, account_ids: list[str] | None) -> list[SignalEvent]:
        return []
