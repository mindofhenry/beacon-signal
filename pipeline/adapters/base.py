"""
Base adapter interface for signal ingestion.

Every signal source gets one adapter. All adapters implement the same
interface so the scoring engine doesn't care where signals come from.

In DEMO_MODE, adapters read from mock JSON files.
In production, adapters call external APIs (6sense, Bombora, CRM, etc).
The scoring engine never knows the difference.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from pydantic import BaseModel


class SignalEvent(BaseModel):
    """
    One signal contribution. This is what every adapter outputs.
    Maps directly to the signal_events table in Supabase.
    """
    account_id: str
    signal_type: str
    signal_value: dict
    weight_applied: float
    reason_text: str
    triggered_at: datetime


class BaseAdapter(ABC):
    """
    Base class for all signal adapters.

    Each adapter:
    1. Fetches raw data from its source (or mock file)
    2. Transforms it into SignalEvent objects
    3. Returns a list of SignalEvents for the scoring engine

    The adapter is responsible for writing reason_text — the human-readable
    explanation that shows up in score breakdowns and alerts.
    """

    def __init__(self, config: dict, demo_mode: bool = True):
        self.config = config
        self.demo_mode = demo_mode

    @abstractmethod
    def fetch_signals(self, account_ids: list[str] | None = None) -> list[SignalEvent]:
        """
        Fetch signals from this source.

        Args:
            account_ids: Optional filter. If None, fetch all available signals.

        Returns:
            List of SignalEvent objects ready for the scoring engine.
        """
        pass

    @abstractmethod
    def get_signal_types(self) -> list[str]:
        """Return the signal types this adapter produces."""
        pass

    def _get_weight(self, signal_subtype: str) -> float:
        """Look up the configured weight for a signal subtype."""
        for category, subtypes in self.config.get("signal_weights", {}).items():
            if isinstance(subtypes, dict) and signal_subtype in subtypes:
                return float(subtypes[signal_subtype])
        return 0.0
