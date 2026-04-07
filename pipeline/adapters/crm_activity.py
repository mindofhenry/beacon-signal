"""
CRM Activity adapter — reads last activity date, open opportunities,
and sequence enrollment status.

Production source: Salesforce, HubSpot CRM.
Demo mode: reads from data/mock_signals.json

NOTE: This adapter will eventually read Loop's CRM tables.
Open Question #1: should Signal read Loop's tables directly
or through a shared view? Stubbed to mock data for now.
"""

from .base import BaseAdapter, SignalEvent


class CRMActivityAdapter(BaseAdapter):

    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        if self.demo_mode:
            return self._load_mock_signals(account_ids)
        raise NotImplementedError("Live CRM integration not built — pending OQ#1 decision")

    def get_signal_types(self) -> list[str]:
        return ["last_activity_recent", "open_opportunity", "sequence_enrolled"]

    def _load_mock_signals(self, account_ids: list[str] | None) -> list[SignalEvent]:
        return []
