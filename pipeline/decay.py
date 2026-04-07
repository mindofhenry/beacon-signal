"""
Time decay utilities — separated from scorer.py so the MCP
get_signal_decay tool and dashboard can use it independently.
"""

import math
from datetime import datetime


def exponential_decay(age_days: float, half_life_days: float) -> float:
    """
    Calculate decay factor using exponential decay.
    Returns value between 0.0 and 1.0.
    1.0 = brand new, 0.5 = one half-life old.
    """
    if half_life_days <= 0:
        return 1.0
    if age_days < 0:
        return 1.0
    return round(math.pow(0.5, age_days / half_life_days), 4)


def get_decayed_weight(
    raw_weight: float,
    triggered_at: datetime,
    as_of: datetime,
    half_life_days: float,
) -> tuple[float, float]:
    """
    Convenience: given a raw weight and timestamps, return
    (decayed_weight, decay_factor).
    """
    age_days = (as_of - triggered_at).total_seconds() / 86400
    factor = exponential_decay(age_days, half_life_days)
    return round(raw_weight * factor, 2), factor
