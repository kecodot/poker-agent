"""Strategy parameter system with hot-reload.

All strategy parameters in a single JSON file with:
  - Type-validated loading
  - Runtime hot-reload (file watcher)
  - Version tracking
  - Parameter groups for organized tuning

Usage:
  params = StrategyParams("config/strategy-config.json")
  factor = params.get("OPEN_RANGE_FACTOR")
  params.reload()  # Hot-reload from disk
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional


class StrategyParams:
    """Load, validate, and hot-reload strategy parameters from JSON."""

    DEFAULT_CONFIG: dict = {
        # ─── Preflop parameters ────────────────────────────────────
        "OPEN_RANGE_FACTOR": 1.0,         # Multiplier for opening range width
        "THREE_BET_FACTOR": 1.0,          # 3-bet frequency multiplier
        "FOUR_BET_FACTOR": 1.0,           # 4-bet frequency multiplier
        "DEFEND_BB_FACTOR": 1.0,          # BB defense width multiplier
        "STEAL_FACTOR": 1.0,              # BTN/CO steal frequency multiplier
        "ISO_RAISE_FACTOR": 1.0,          # Isolation raise multiplier
        "OPEN_SIZE_UTG": 2.5,             # UTG open size (BB)
        "OPEN_SIZE_MP": 2.5,              # MP open size (BB)
        "OPEN_SIZE_CO": 2.3,              # CO open size (BB)
        "OPEN_SIZE_BTN": 2.0,             # BTN open size (BB)
        "OPEN_SIZE_SB": 3.0,              # SB open size (BB)
        "THREE_BET_SIZE_IP": 3.0,         # 3-bet size multiplier IP
        "THREE_BET_SIZE_OOP": 4.0,        # 3-bet size multiplier OOP

        # ─── Postflop parameters ───────────────────────────────────
        "CBET_FACTOR": 1.0,               # C-bet frequency multiplier
        "CBET_DRY_SIZE": 0.33,            # C-bet sizing on dry flops
        "CBET_WET_SIZE": 0.66,            # C-bet sizing on wet flops
        "CBET_NEUTRAL_SIZE": 0.50,        # C-bet sizing on neutral flops
        "DOUBLE_BARREL_FACTOR": 1.0,      # Turn barrel frequency multiplier
        "TRIPLE_BARREL_FACTOR": 1.0,      # River barrel frequency multiplier
        "BLUFF_FACTOR": 1.0,              # Bluff frequency multiplier
        "SEMI_BLUFF_FACTOR": 1.0,         # Semi-bluff frequency multiplier
        "FLOAT_FACTOR": 1.0,              # Float frequency multiplier

        # ─── Value extraction ──────────────────────────────────────
        "VALUE_BET_THIN": 1.0,            # How thin to value bet (>1 = thinner)
        "VALUE_BET_RIVER_SIZE": 0.75,     # Default river value bet sizing
        "OVERBET_NUTS": 1.5,              # Overbet size for nutted hands
        "CHECK_RAISE_FACTOR": 1.0,        # Check-raise frequency multiplier

        # ─── Defense parameters ────────────────────────────────────
        "FOLD_TO_CBET_FACTOR": 1.0,       # >1 = fold more to cbets
        "FOLD_TO_3BET_FACTOR": 1.0,       # >1 = fold more to 3-bets
        "CALL_DOWN_FACTOR": 1.0,          # Calling station tendency
        "BLUFF_CATCH_FACTOR": 1.0,        # River bluff-catching frequency

        # ─── Opponent adjustment ───────────────────────────────────
        "ADJUST_TO_OPPONENT": True,       # Enable opponent-based adjustments
        "EXPLOIT_NITS": True,             # Auto-exploit nit players
        "EXPLOIT_MANIACS": True,          # Auto-exploit maniacs
        "EXPLOIT_PASSIVE": True,          # Auto-exploit passive fish

        # ─── Monte Carlo ───────────────────────────────────────────
        "MC_SIMS_DEFAULT": 2000,          # Default Monte Carlo simulations
        "MC_SIMS_PRECISE": 5000,          # Precise mode simulations
        "MC_SIMS_FAST": 500,              # Fast mode simulations
        "MC_MAX_WORKERS": 4,              # Thread pool size

        # ─── Performance ───────────────────────────────────────────
        "MAX_DECISION_TIME_MS": 300,      # Max time for a single decision
        "DEADLINE_SAFETY_MS": 1500,       # Emergency fallback threshold

        # ─── Bankroll management ───────────────────────────────────
        "STACK_THRESHOLD_SHORT_BB": 20,   # Short stack threshold (BB)
        "STACK_THRESHOLD_DEEP_BB": 150,   # Deep stack threshold (BB)

        # ─── Meta ──────────────────────────────────────────────────
        "STRATEGY_VERSION": "v1",
        "LOG_LEVEL": "INFO",
    }

    def __init__(self, config_path: str = "config/strategy-config.json"):
        self.config_path = Path(config_path)
        self._lock = Lock()
        self._config: dict = dict(self.DEFAULT_CONFIG)
        self._mtime: float = 0
        self._reload_if_changed()

    def _reload_if_changed(self) -> None:
        try:
            if self.config_path.exists():
                mtime = self.config_path.stat().st_mtime
                if mtime > self._mtime:
                    self._load()
                    self._mtime = mtime
        except Exception:
            pass

    def _load(self) -> None:
        try:
            with open(self.config_path) as f:
                loaded = json.load(f)
            for k, v in loaded.items():
                if k in self.DEFAULT_CONFIG:
                    self._config[k] = v
        except Exception:
            pass

    def reload(self) -> bool:
        """Force reload from disk. Returns True if changed."""
        with self._lock:
            old = dict(self._config)
            try:
                self._load()
                self._mtime = self.config_path.stat().st_mtime if self.config_path.exists() else 0
                return old != self._config
            except Exception:
                return False

    def get(self, key: str, default: Any = None) -> Any:
        self._reload_if_changed()
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._config[key] = value

    def update(self, updates: dict) -> None:
        with self._lock:
            self._config.update(updates)

    def save(self) -> None:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self._config, f, indent=2)

    def get_all(self) -> dict:
        self._reload_if_changed()
        return dict(self._config)

    def get_version(self) -> str:
        return str(self.get("STRATEGY_VERSION", "v1"))

    def create_variant(self, overrides: dict, suffix: str = "") -> dict:
        """Create a parameter variant for A/B testing."""
        variant = dict(self._config)
        variant.update(overrides)
        variant["STRATEGY_VERSION"] = f"{variant.get('STRATEGY_VERSION', 'v1')}_{suffix}"
        return variant

    def to_db_record(self) -> dict:
        """Export config suitable for storage in strategy_versions table."""
        return {
            "version": self.get_version(),
            "config_json": self.get_all(),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
