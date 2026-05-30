"""Strategy Evolution — automated A/B/C testing and version management.

Every 1000 hands:
  1. Generate Strategy A, Strategy B, Strategy C variants
  2. Track performance of each variant
  3. Auto-retain best version
  4. Eliminate worst version
  5. Feed winner back as baseline for next cycle
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class StrategyEvolution:
    """Automated strategy experimentation and evolution."""

    def __init__(self, db=None, strategy_params=None, output_dir: str = "reports"):
        self.db = db
        self.strategy_params = strategy_params
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.evolution_state_path = self.output_dir / "evolution_state.json"
        self._state = self._load_state()

    def set_db(self, db):
        self.db = db

    def set_params(self, params):
        self.strategy_params = params

    def _load_state(self) -> dict:
        if self.evolution_state_path.exists():
            try:
                return json.loads(self.evolution_state_path.read_text())
            except Exception:
                pass
        return {
            "generation": 0,
            "hands_at_last_cycle": 0,
            "active_variants": [],
            "history": [],
            "best_version": None,
            "best_bb_per_100": None,
        }

    def _save_state(self) -> None:
        self.evolution_state_path.write_text(json.dumps(self._state, indent=2))

    def _get_hand_count(self) -> int:
        if self.db:
            return self.db.get_hand_count()
        return 0

    def should_evolve(self, interval: int = 1000) -> bool:
        """Check if enough hands have been played to trigger evolution."""
        current = self._get_hand_count()
        last = self._state.get("hands_at_last_cycle", 0)
        return current - last >= interval

    def generate_variants(self, n: int = 3) -> list[dict]:
        """Generate N strategy variants from current baseline.

        Variant A: Aggressive — higher cbet, bluff, steal
        Variant B: Defensive — lower fold frequencies, higher call-down
        Variant C: Balanced — small adjustments to key params
        """
        if self.strategy_params:
            base = self.strategy_params.get_all()
        else:
            base = {}

        gen = self._state.get("generation", 0)
        variants = []

        profiles = [
            {
                "suffix": "aggressive",
                "overrides": {
                    "CBET_FACTOR": min(1.5, base.get("CBET_FACTOR", 1.0) * 1.2),
                    "BLUFF_FACTOR": min(1.5, base.get("BLUFF_FACTOR", 1.0) * 1.25),
                    "STEAL_FACTOR": min(2.0, base.get("STEAL_FACTOR", 1.0) * 1.15),
                    "THREE_BET_FACTOR": min(2.0, base.get("THREE_BET_FACTOR", 1.0) * 1.1),
                    "SEMI_BLUFF_FACTOR": min(1.5, base.get("SEMI_BLUFF_FACTOR", 1.0) * 1.2),
                },
            },
            {
                "suffix": "defensive",
                "overrides": {
                    "FOLD_TO_CBET_FACTOR": max(0.5, base.get("FOLD_TO_CBET_FACTOR", 1.0) * 0.85),
                    "FOLD_TO_3BET_FACTOR": max(0.5, base.get("FOLD_TO_3BET_FACTOR", 1.0) * 0.9),
                    "CALL_DOWN_FACTOR": min(2.0, base.get("CALL_DOWN_FACTOR", 1.0) * 1.15),
                    "BLUFF_CATCH_FACTOR": min(2.0, base.get("BLUFF_CATCH_FACTOR", 1.0) * 1.2),
                    "CBET_FACTOR": max(0.3, base.get("CBET_FACTOR", 1.0) * 0.9),
                },
            },
            {
                "suffix": "balanced",
                "overrides": {
                    "VALUE_BET_THIN": min(1.5, base.get("VALUE_BET_THIN", 1.0) * 1.1),
                    "CHECK_RAISE_FACTOR": min(1.5, base.get("CHECK_RAISE_FACTOR", 1.0) * 1.1),
                    "DOUBLE_BARREL_FACTOR": base.get("DOUBLE_BARREL_FACTOR", 1.0),
                    "FLOAT_FACTOR": min(1.5, base.get("FLOAT_FACTOR", 1.0) * 1.1),
                },
            },
        ]

        for i, profile in enumerate(profiles[:n]):
            version = f"v{gen}_{chr(65 + i)}_{profile['suffix']}"
            overrides = profile["overrides"]
            variant_config = self.strategy_params.create_variant(
                overrides, suffix=f"{gen}_{chr(65 + i)}"
            )
            variants.append({
                "version": version,
                "profile": profile["suffix"],
                "overrides": overrides,
                "config": variant_config,
            })

        return variants

    def run_evolution_cycle(self) -> dict:
        """Execute one evolution cycle: generate, evaluate, select."""
        if not self.db:
            return {"error": "no database connected"}

        current_hands = self._get_hand_count()
        if current_hands < 100:
            return {"error": "need at least 100 hands", "current_hands": current_hands}

        gen = self._state.get("generation", 0)
        variants = self.generate_variants(3)

        # Score each variant using the parameter optimizer's heuristic
        from ..optimizer.parameter_optimizer import ParameterOptimizer
        optimizer = ParameterOptimizer(self.db, self.strategy_params, str(self.output_dir))

        scored = []
        for v in variants:
            sv = optimizer.score_variant(v, min(current_hands, 5000))
            scored.append(sv)

        # Rank by score
        ranked = sorted(scored, key=lambda x: x.get("score", 0), reverse=True)
        best = ranked[0] if ranked else None
        worst = ranked[-1] if ranked else None

        # Update evolution state
        self._state["generation"] = gen + 1
        self._state["hands_at_last_cycle"] = current_hands
        self._state["active_variants"] = [
            {"version": r["version"], "score": r.get("score", 0),
             "bb_per_100": r.get("estimated_bb_per_100", 0)}
            for r in ranked
        ]

        cycle_result = {
            "cycle": gen + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hands_at_cycle": current_hands,
            "variants_tested": len(scored),
            "best": {
                "version": best["version"],
                "profile": best.get("profile", ""),
                "estimated_bb_per_100": best.get("estimated_bb_per_100", 0),
                "score": best.get("score", 0),
                "overrides": best.get("overrides", {}),
            },
            "worst": {
                "version": worst["version"] if worst else "N/A",
                "estimated_bb_per_100": worst.get("estimated_bb_per_100", 0) if worst else 0,
            },
            "ranking": [
                {
                    "rank": i + 1,
                    "version": r["version"],
                    "profile": r.get("profile", ""),
                    "estimated_bb_per_100": r.get("estimated_bb_per_100", 0),
                    "score": r.get("score", 0),
                }
                for i, r in enumerate(ranked)
            ],
        }

        # Update best version in history
        if best and (
            self._state["best_bb_per_100"] is None
            or best.get("estimated_bb_per_100", 0) > (self._state["best_bb_per_100"] or -999)
        ):
            self._state["best_version"] = best["version"]
            self._state["best_bb_per_100"] = best["estimated_bb_per_100"]

        self._state["history"].append(cycle_result)
        # Keep only last 20 cycles
        if len(self._state["history"]) > 20:
            self._state["history"] = self._state["history"][-20:]

        # Auto-apply best variant if significantly better
        if best and best.get("score", 0) > 0:
            self._apply_best_variant(best)

        self._save_state()
        return cycle_result

    def _apply_best_variant(self, best: dict) -> None:
        """Persist the best strategy variant to config."""
        if not self.strategy_params:
            return

        overrides = best.get("overrides", {})
        for k, v in overrides.items():
            self.strategy_params.set(k, v)

        self.strategy_params.set("STRATEGY_VERSION", best.get("version", "v-evolved"))
        self.strategy_params.save()

        # Also save to DB
        if self.db:
            self.db.save_strategy_version(
                version=best.get("version", "v-evolved"),
                config=self.strategy_params.get_all(),
                is_active=True,
            )

    def get_status(self) -> dict:
        """Get current evolution status."""
        return {
            "generation": self._state.get("generation", 0),
            "hands_at_last_cycle": self._state.get("hands_at_last_cycle", 0),
            "current_hands": self._get_hand_count(),
            "best_version": self._state.get("best_version", "none"),
            "best_bb_per_100": self._state.get("best_bb_per_100", 0),
            "active_variants": self._state.get("active_variants", []),
            "recent_cycles": self._state.get("history", [])[-5:],
        }

    def save_report(self) -> str:
        """Save evolution status and history as JSON."""
        status = self.get_status()
        path = self.output_dir / "evolution_report.json"
        path.write_text(json.dumps(status, indent=2))
        return str(path)
