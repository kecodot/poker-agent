"""Backtesting Framework.

Replays historical hands with new strategy parameters to compare:
  - EV differences between strategy versions
  - BB/100 differences
  - ROI differences
  - Win rate differences

Supports A/B testing without risking real chips.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class BacktestEngine:
    """Replay historical hands with modified strategy parameters."""

    def __init__(self, db=None, output_dir: str = "reports"):
        self.db = db
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_db(self, db):
        self.db = db

    def _require_db(self):
        if self.db is None:
            raise RuntimeError("BacktestEngine: no database set.")

    def backtest_parameter_change(
        self,
        param_name: str,
        old_value: float,
        new_value: float,
        n_hands: int = 500,
    ) -> dict:
        """Estimate the effect of changing a single parameter.

        Uses a heuristic model based on the parameter's influence on decision-making.
        Since we can't replay exact hands (decisions would change the game tree),
        we estimate based on action distributions and opponent behavior patterns.
        """
        self._require_db()
        hands = self.db.get_recent_hands(n_hands)
        if not hands:
            return {"error": "no hands available", "hands_analyzed": 0}

        delta = new_value - old_value
        ratio = new_value / max(old_value, 0.01)

        # Build impact model per parameter
        impact_models = {
            "CBET_FACTOR": self._estimate_cbet_impact,
            "BLUFF_FACTOR": self._estimate_bluff_impact,
            "FOLD_TO_CBET_FACTOR": self._estimate_fold_impact,
            "FOLD_TO_3BET_FACTOR": self._estimate_fold_impact,
            "STEAL_FACTOR": self._estimate_steal_impact,
            "THREE_BET_FACTOR": self._estimate_3bet_impact,
            "DOUBLE_BARREL_FACTOR": self._estimate_barrel_impact,
            "TRIPLE_BARREL_FACTOR": self._estimate_barrel_impact,
            "CALL_DOWN_FACTOR": self._estimate_calldown_impact,
            "BLUFF_CATCH_FACTOR": self._estimate_bluffcatch_impact,
            "VALUE_BET_THIN": self._estimate_valuebet_impact,
            "CHECK_RAISE_FACTOR": self._estimate_checkraise_impact,
            "FLOAT_FACTOR": self._estimate_float_impact,
            "SEMI_BLUFF_FACTOR": self._estimate_semibluff_impact,
        }

        estimator = impact_models.get(param_name, self._estimate_generic_impact)
        impact = estimator(hands, delta, ratio)

        # Get current baseline
        baseline = self.db.get_stats_for_n_hands(n_hands)
        current_bb100 = baseline.get("bb_per_100", 0)

        estimated_bb100 = current_bb100 + impact.get("estimated_bb100_delta", 0)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parameter": param_name,
            "old_value": old_value,
            "new_value": new_value,
            "delta": round(delta, 3),
            "ratio": round(ratio, 3),
            "hands_analyzed": len(hands),
            "current_bb_per_100": round(current_bb100, 2),
            "estimated_bb_per_100": round(estimated_bb100, 2),
            "estimated_delta": round(impact.get("estimated_bb100_delta", 0), 2),
            "confidence": round(impact.get("confidence", 0.3), 3),
            "explanation": impact.get("explanation", ""),
            "recommendation": "apply" if impact.get("estimated_bb100_delta", 0) > 0 else "reject",
        }

    def _estimate_cbet_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        """Higher CBET → more folds from opponents, but more risk when called."""
        # Count flops seen and cbet opportunities
        flop_hands = [h for h in hands if h.get("street_reached") not in ("Preflop",)]
        if not flop_hands:
            return {"estimated_bb100_delta": 0, "confidence": 0.1, "explanation": "no flop data"}

        # Check opponent fold-to-cbet tendencies
        opponents = self.db.get_all_opponents(min_hands=5)
        avg_fcb = 0.5
        for o in opponents:
            fo = o.get("fold_to_cbet_opps", 0)
            fa = o.get("fold_to_cbet_actions", 0)
            if fo > 0:
                avg_fcb = max(avg_fcb, fa / fo) if fa / fo > avg_fcb else avg_fcb

        # Model: each cbet generates fold equity. Higher delta → more cbets.
        # If opponents fold >50%, more cbets = more +EV
        # If opponents fold <40%, more cbets could be -EV
        hands_bb = len(flop_hands) / max(len(hands), 1)
        impact = delta * hands_bb * (avg_fcb - 0.45) * 15

        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": round(min(0.8, len(flop_hands) / 1000), 3),
            "explanation": (
                f"Changing CBET_FACTOR from 1.0 by {delta:+.2f}. "
                f"Opponents fold to cbet {avg_fcb:.0%}. "
                f"{'Favorable' if impact > 0 else 'Unfavorable'} for increased cbetting."
            ),
        }

    def _estimate_bluff_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        """Higher bluff → more fold equity, but bluff-catching opponents = disaster."""
        river_hands = [h for h in hands if h.get("street_reached") == "River"]
        if not river_hands:
            return {"estimated_bb100_delta": 0, "confidence": 0.1, "explanation": "no river data"}

        # Check how often river bets succeed
        conn = self.db._get_conn()
        river_bets = 0
        river_bets_won = 0
        for h in river_hands:
            actions = conn.execute(
                "SELECT action FROM actions WHERE hand_id=? AND street='River'",
                (h["hand_id"],)
            ).fetchall()
            for a in actions:
                if a["action"] in ("bet", "raise"):
                    river_bets += 1
                    if h.get("chip_delta", 0) > 0:
                        river_bets_won += 1

        success_rate = river_bets_won / max(river_bets, 1)
        river_freq = len(river_hands) / max(len(hands), 1)

        impact = delta * river_freq * (success_rate - 0.45) * 20

        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": round(min(0.8, river_bets / 50), 3),
            "explanation": (
                f"River bet success rate: {success_rate:.0%}. "
                f"{'Good conditions' if success_rate > 0.5 else 'Poor conditions'} for bluffing."
            ),
        }

    def _estimate_fold_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        """Higher fold → save chips short-term, but could be exploited."""
        # Fold more = save chips, but lose pots we could have won
        # Negative delta (fold less) could be +EV if we have good equity
        fold_count = 0
        for h in hands:
            if h.get("chip_delta", 0) == 0:
                fold_count += 1

        fold_pct = fold_count / max(len(hands), 1)

        # If we're folding a lot and losing, folding less could help
        impact = -delta * fold_pct * 10  # negative delta (fold less) = positive impact

        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.4,
            "explanation": (
                f"Current fold rate: {fold_pct:.0%}. "
                f"{'Consider folding less' if delta < 0 else 'Consider folding more'}."
            ),
        }

    def _estimate_steal_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        """Higher steal → more blind wins from LP."""
        btn_hands = [h for h in hands if h.get("position") == "BTN"]
        co_hands = [h for h in hands if h.get("position") == "CO"]
        lp_total = len(btn_hands) + len(co_hands)
        lp_win = sum(1 for h in btn_hands + co_hands if h.get("chip_delta", 0) > 0)

        lp_win_rate = lp_win / max(lp_total, 1)
        lp_freq = lp_total / max(len(hands), 1)

        impact = delta * lp_freq * lp_win_rate * 12

        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": round(min(0.7, lp_total / 200), 3),
            "explanation": (
                f"LP (BTN/CO) win rate: {lp_win_rate:.0%}. "
                f"{'Expanding steal range' if delta > 0 else 'Reducing steal range'} "
                f"{'recommended' if impact > 0 else 'not recommended'}."
            ),
        }

    def _estimate_3bet_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = delta * 3
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.3,
            "explanation": "3-bet frequency change — effectiveness depends on opponent fold-to-3bet rates.",
        }

    def _estimate_barrel_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        turn_river_hands = [h for h in hands if h.get("street_reached") in ("Turn", "River")]
        freq = len(turn_river_hands) / max(len(hands), 1)
        impact = delta * freq * 4
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": min(0.5, len(turn_river_hands) / 500),
            "explanation": "Barrel frequency — more barrels = more pressure, but more risk.",
        }

    def _estimate_calldown_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = -delta * 2  # calling down more often = slightly -EV usually
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.3,
            "explanation": "Call-down frequency — calling more increases variance.",
        }

    def _estimate_bluffcatch_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        river_hands = [h for h in hands if h.get("street_reached") == "River"]
        freq = len(river_hands) / max(len(hands), 1)
        impact = delta * freq * 3
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": min(0.5, len(river_hands) / 200),
            "explanation": "Bluff-catching frequency — good if opponents bluff too much.",
        }

    def _estimate_valuebet_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = delta * 5
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.4,
            "explanation": "Thin value betting — extracts more from calling stations.",
        }

    def _estimate_checkraise_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = delta * 2
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.2,
            "explanation": "Check-raise frequency — balances aggression when OOP.",
        }

    def _estimate_float_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = delta * 2.5
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.25,
            "explanation": "Float frequency — calling cbets IP to steal on later streets.",
        }

    def _estimate_semibluff_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = delta * 3
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.3,
            "explanation": "Semi-bluff frequency — betting draws for fold equity + realized equity.",
        }

    def _estimate_generic_impact(self, hands: list[dict], delta: float, ratio: float) -> dict:
        impact = delta * 2
        return {
            "estimated_bb100_delta": round(impact, 2),
            "confidence": 0.15,
            "explanation": "Generic parameter impact — low confidence estimate.",
        }

    def compare_versions(
        self,
        old_params: dict,
        new_params: dict,
        n_hands: int = 1000,
    ) -> dict:
        """Compare two strategy versions by estimating each parameter change."""
        self._require_db()

        results = []
        total_delta = 0.0

        for key in new_params:
            if key in old_params and old_params[key] != new_params[key]:
                bt = self.backtest_parameter_change(
                    key, old_params[key], new_params[key], n_hands
                )
                results.append(bt)
                total_delta += bt.get("estimated_delta", 0)

        # Get current baseline
        baseline = self.db.get_stats_for_n_hands(n_hands)
        current_bb100 = baseline.get("bb_per_100", 0)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hands_analyzed": len(self.db.get_recent_hands(n_hands)),
            "old_version": old_params.get("STRATEGY_VERSION", "v-old"),
            "new_version": new_params.get("STRATEGY_VERSION", "v-new"),
            "old_bb_per_100": round(current_bb100, 2),
            "estimated_new_bb_per_100": round(current_bb100 + total_delta, 2),
            "estimated_delta": round(total_delta, 2),
            "parameter_changes": results,
            "recommendation": "apply" if total_delta > 1 else ("reject" if total_delta < -1 else "neutral"),
        }

    def save_backtest_report(self, old_params: dict = None, new_params: dict = None,
                            n_hands: int = 1000) -> str:
        """Run and save backtest comparison report."""
        if old_params is None:
            old_params = {}
        if new_params is None:
            new_params = {}

        report = self.compare_versions(old_params, new_params, n_hands)
        path = self.output_dir / "backtest-report.json"
        path.write_text(json.dumps(report, indent=2))
        return str(path)
