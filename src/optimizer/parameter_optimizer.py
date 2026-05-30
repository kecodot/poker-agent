"""Parameter Optimizer — automatic parameter tuning from hand history.

Reads last N hands, evaluates current params, generates and ranks variants.
Outputs strategy-ranking.json with scored strategy versions.
"""

from __future__ import annotations

import itertools
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class ParameterOptimizer:
    """Optimize strategy parameters by analyzing historical results."""

    # Parameters to optimize and their search ranges
    TUNABLE_PARAMS = {
        "CBET_FACTOR": (0.3, 1.5, 0.1),
        "BLUFF_FACTOR": (0.2, 1.5, 0.1),
        "FLOAT_FACTOR": (0.3, 1.5, 0.1),
        "DOUBLE_BARREL_FACTOR": (0.3, 1.5, 0.1),
        "TRIPLE_BARREL_FACTOR": (0.2, 1.5, 0.1),
        "FOLD_TO_CBET_FACTOR": (0.5, 2.0, 0.1),
        "FOLD_TO_3BET_FACTOR": (0.5, 2.0, 0.1),
        "CALL_DOWN_FACTOR": (0.3, 2.0, 0.1),
        "BLUFF_CATCH_FACTOR": (0.3, 2.0, 0.1),
        "STEAL_FACTOR": (0.5, 2.0, 0.1),
        "THREE_BET_FACTOR": (0.5, 2.0, 0.1),
        "VALUE_BET_THIN": (0.5, 1.5, 0.05),
        "CHECK_RAISE_FACTOR": (0.3, 1.5, 0.1),
        "SEMI_BLUFF_FACTOR": (0.3, 1.5, 0.1),
    }

    def __init__(self, db=None, strategy_params=None, output_dir: str = "reports"):
        self.db = db
        self.strategy_params = strategy_params
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_db(self, db):
        self.db = db

    def set_params(self, params):
        self.strategy_params = params

    def _require_db(self):
        if self.db is None:
            raise RuntimeError("ParameterOptimizer: no database set.")

    def _get_hand_stats(self, n: int = 5000) -> dict:
        """Get baseline stats from last N hands."""
        self._require_db()
        return self.db.get_stats_for_n_hands(n)

    def score_current_params(self, n: int = 5000) -> dict:
        """Score the current parameters based on recent results."""
        stats = self._get_hand_stats(n)
        if not stats or stats.get("hands", 0) < 10:
            return {"version": "current", "score": 0, "message": "insufficient data"}

        bb100 = stats.get("bb_per_100", 0)
        win_rate = stats.get("win_rate", 0)
        hands = stats.get("hands", 1)

        # Composite score: weighted combination of BB/100 and win rate
        # Higher BB/100 is better but also reward consistency (win rate)
        score = bb100 * 0.7 + win_rate * 30 + (1.0 / max(abs(bb100), 1)) * 2

        return {
            "version": self.strategy_params.get_version() if self.strategy_params else "v1",
            "hands_evaluated": hands,
            "bb_per_100": bb100,
            "win_rate": round(win_rate, 4),
            "score": round(score, 3),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def generate_variants(self, base_config: dict, n_variants: int = 10) -> list[dict]:
        """Generate parameter variants by perturbing key parameters.

        Uses Latin Hypercube-style sampling over the tunable parameter space.
        """
        variants = []
        rng = random.Random()

        for i in range(n_variants):
            variant = dict(base_config)
            overrides = {}

            # Pick 2-4 parameters to vary per variant
            params_to_vary = rng.sample(
                list(self.TUNABLE_PARAMS.keys()),
                min(rng.randint(2, 4), len(self.TUNABLE_PARAMS))
            )

            for param in params_to_vary:
                lo, hi, step = self.TUNABLE_PARAMS[param]
                current = variant.get(param, 1.0)
                # Perturb by ±0.1 to ±0.3 depending on range
                delta = rng.uniform(-0.3, 0.3) * (hi - lo)
                new_val = round(max(lo, min(hi, current * (1 + delta))), 2)
                overrides[param] = new_val
                variant[param] = new_val

            variants.append({
                "version": f"v{i + 1}_auto",
                "overrides": overrides,
                "config": variant,
                "parent_version": base_config.get("STRATEGY_VERSION", "v1"),
            })

        return variants

    def score_variant(self, variant: dict, n: int = 5000) -> dict:
        """Estimate variant performance based on historical data heuristics.

        Since we can't actually replay hands with new params without a full
        backtest, we use a heuristic scoring model based on parameter analysis:

        - Higher CBET_FACTOR on dry boards → +EV if fold_to_cbet is high
        - Higher BLUFF_FACTOR → +EV if opponents fold too much
        - Lower FOLD_TO_CBET → +EV if our equity is decent
        - Higher STEAL_FACTOR → +EV from LP (CO/BTN)
        """
        self._require_db()
        overrides = variant.get("overrides", {})

        # Get baseline stats
        pos_stats = self.db.get_position_stats(n)
        hands = self.db.get_recent_hands(n)

        if not hands:
            return {**variant, "bb_per_100": 0, "score": 0, "message": "no data"}

        # Heuristic scoring: adjust from baseline
        base_bb100 = self.db.get_stats_for_n_hands(n).get("bb_per_100", 0)

        score_delta = 0.0

        # 1. CBet factor: reward higher cbet if opponents fold to cbet a lot
        if "CBET_FACTOR" in overrides:
            delta = overrides["CBET_FACTOR"] - 1.0
            # Check opponent fold-to-cbet from database
            opponents = self.db.get_all_opponents(min_hands=10)
            avg_fcb = 0.5
            if opponents:
                fold_rates = []
                for o in opponents:
                    fo = o.get("fold_to_cbet_opps", 0)
                    fa = o.get("fold_to_cbet_actions", 0)
                    if fo > 0:
                        fold_rates.append(fa / fo)
                if fold_rates:
                    avg_fcb = sum(fold_rates) / len(fold_rates)

            if avg_fcb > 0.5 and delta > 0:
                score_delta += delta * (avg_fcb - 0.5) * 5
            elif avg_fcb < 0.4 and delta > 0:
                score_delta -= delta * 2

        # 2. Bluff factor: reward if opponents fold a lot
        if "BLUFF_FACTOR" in overrides:
            delta = overrides["BLUFF_FACTOR"] - 1.0
            # Higher delta → +EV if opponents have high fold%
            fold_pct = sum(1 for h in hands if h.get("chip_delta", 0) == 0) / max(len(hands), 1)
            if fold_pct < 0.3 and delta > 0:
                score_delta += delta * 3  # Opponents fold often, bluffing works
            elif fold_pct > 0.5 and delta > 0:
                score_delta -= delta * 2  # Opponents call, bluffing fails

        # 3. Fold to cbet: lower = call more cbets
        if "FOLD_TO_CBET_FACTOR" in overrides:
            delta = 1.0 - overrides["FOLD_TO_CBET_FACTOR"]
            # Calling more cbets is good if our postflop equity is decent
            score_delta += delta * 1.5

        # 4. Steal factor: higher = steal more
        if "STEAL_FACTOR" in overrides:
            delta = overrides["STEAL_FACTOR"] - 1.0
            # Stealing from BTN/CO is +EV
            btn_stats = pos_stats.get("BTN", {})
            co_stats = pos_stats.get("CO", {})
            lp_win = (btn_stats.get("win_rate", 0) + co_stats.get("win_rate", 0)) / 2
            if lp_win > 0.4:
                score_delta += delta * 4
            else:
                score_delta += delta * 1

        # 5. Value bet thin: more value = more profit on rivers
        if "VALUE_BET_THIN" in overrides:
            delta = overrides["VALUE_BET_THIN"] - 1.0
            # Higher thin value = more profit if opponents call wide
            opponents = self.db.get_all_opponents(min_hands=5)
            call_wide = False
            for o in opponents:
                if o.get("archetype") in ("Calling Station", "LAG", "Maniac", "Whale"):
                    call_wide = True
                    break
            if call_wide:
                score_delta += delta * 3
            else:
                score_delta += delta * 0.5

        # 6. Three bet factor
        if "THREE_BET_FACTOR" in overrides:
            delta = overrides["THREE_BET_FACTOR"] - 1.0
            score_delta += delta * 2

        # 7. Call down factor
        if "CALL_DOWN_FACTOR" in overrides:
            delta = overrides["CALL_DOWN_FACTOR"] - 1.0
            if base_bb100 > 0:
                score_delta -= delta * 1  # If winning, don't call down more
            else:
                score_delta += delta * 0.5

        # 8. Double barrel
        if "DOUBLE_BARREL_FACTOR" in overrides:
            delta = overrides["DOUBLE_BARREL_FACTOR"] - 1.0
            score_delta += delta * 1.5

        estimated_bb100 = base_bb100 + score_delta
        confidence = max(0.1, min(0.95, len(hands) / 10000))

        return {
            **variant,
            "estimated_bb_per_100": round(estimated_bb100, 2),
            "delta_from_baseline": round(score_delta, 2),
            "confidence": round(confidence, 3),
            "score": round(estimated_bb100 * 0.7 + score_delta * 0.3, 3),
        }

    def optimize(self, n_hands: int = 5000, n_variants: int = 15) -> dict:
        """Run full optimization: generate variants, score them, rank them."""
        self._require_db()

        # Get base config
        if self.strategy_params:
            base_config = self.strategy_params.get_all()
        else:
            base_config = {}

        if not base_config:
            return {"error": "no strategy parameters configured"}

        # Score current
        current_score = self.score_current_params(n_hands)

        # Generate variants
        variants = self.generate_variants(base_config, n_variants)

        # Score all variants
        scored = []
        for v in variants:
            sv = self.score_variant(v, n_hands)
            scored.append(sv)

        # Sort by score descending
        ranked = sorted(scored, key=lambda x: x.get("score", 0), reverse=True)

        # Build ranking
        ranking = []
        for i, v in enumerate(ranked):
            ranking.append({
                "rank": i + 1,
                "version": v.get("version", "?"),
                "parent_version": v.get("parent_version", "v1"),
                "estimated_bb_per_100": v.get("estimated_bb_per_100", 0),
                "delta_from_baseline": v.get("delta_from_baseline", 0),
                "confidence": v.get("confidence", 0),
                "score": v.get("score", 0),
                "overrides": v.get("overrides", {}),
            })

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hands_evaluated": current_score.get("hands_evaluated", 0),
            "baseline": current_score,
            "top_variants": ranking[:5],
            "all_variants": ranking,
        }

        return result

    def save_ranking(self, n_hands: int = 5000, n_variants: int = 15) -> str:
        """Run optimization and save strategy-ranking.json."""
        result = self.optimize(n_hands, n_variants)
        path = self.output_dir / "strategy-ranking.json"
        path.write_text(json.dumps(result, indent=2))
        return str(path)
