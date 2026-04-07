"""
Config loader — reads weights.yaml and alert_thresholds.yaml.
"""

import os
import yaml
from pathlib import Path


def load_weights_config() -> dict:
    """Load signal weights from config/weights.yaml."""
    config_path = Path(__file__).parent.parent / "config" / "weights.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_alert_config() -> dict:
    """Load alert thresholds from config/alert_thresholds.yaml."""
    config_path = Path(__file__).parent.parent / "config" / "alert_thresholds.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def is_demo_mode() -> bool:
    """Check if running in demo mode."""
    return os.environ.get("DEMO_MODE", "true").lower() == "true"
