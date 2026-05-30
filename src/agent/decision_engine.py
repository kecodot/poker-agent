"""Decision engine — continuous strategy mixing pipeline.

The decision engine:
  1. Extracts game state from the table dict
  2. Classifies opponent pool (passive/aggressive/mixed)
  3. Computes contextual strategy weights via StrategyMixer
  4. Runs all three strategies and blends via weighted voting
  5. Validates the action against allowed actions
  6. Generates Arena-compliant reasoning with explainer log
"""

from __future__ import annotations

import random
import time
from typing import Optional

from ..engine.hand_evaluator import _hand_class, static_preflop_equity
from ..engine.equity_calculator import compute_full_equity, compute_pot_odds
from ..engine.range_engine import seat_to_position, hand_class
from ..engine.opponent_model import OpponentModel
from ..strategy.strategy_router import (
    classify_and_select,
    MODE_LIMP_VALUE,
    MODE_RAISE_EXPLOIT,
    MODE_HYBRID,
)
from ..strategy.strategy_mixer import StrategyMixer, StrategyVote, BlendedDecision

FALLBACK_REASONING = '{vr: "std", ke: "legal", pp: "pot control"}'

# Track which strategy mode is dominant (for performance evaluation)
_active_strategy_mode: str = MODE_HYBRID
_active_pool_classification: Optional[dict] = None
_active_strategy_weights: dict[str, float] = {"limp_value": 0.33, "raise_exploit": 0.33, "hybrid": 0.34}


def get_active_mode() -> str:
    """Return the dominant strategy mode (highest weight)."""
    global _active_strategy_weights
    w = _active_strategy_weights
    if not w:
        return MODE_HYBRID
    return max(w, key=w.get)


def get_active_pool() -> Optional[dict]:
    """Return the current pool classification."""
    return _active_pool_classification


def get_active_weights() -> dict[str, float]:
    """Return the current strategy weights for explainability."""
    return dict(_active_strategy_weights)


class DecisionEngine:
    """Central decision maker that orchestrates all strategy modules."""

    def __init__(
        self,
        opponent_model: Optional[OpponentModel] = None,
        config: Optional[dict] = None,
    ):
        self.opponent_model = opponent_model or OpponentModel()
        self.config = config or {}
        self.decision_count = 0
        self.total_decision_time_ms = 0.0
        self.mixer = StrategyMixer()

    def decide(self, table: dict, deadline_s: float = 10.0) -> dict:
        """Main decision function — Arena-compatible interface.

        Args:
            table: Arena table dict from /texas/pending-actions
            deadline_s: Seconds until action deadline

        Returns:
            Arena-compatible action dict: {action, amount?, message, reasoning}
        """
        t0 = time.perf_counter()

        # ─── Deadline safety ───────────────────────────────────────
        if deadline_s < 1.5:
            action = self._deadline_action(table)
            self._record_timing(t0)
            return action

        # ─── Extract game state ────────────────────────────────────
        allowed = table.get("allowedActions") or {}
        available = allowed.get("availableActions") or []

        self_seat_num = table.get("selfSeatNumber")
        seats = table.get("seats") or []
        self_seat = next((s for s in seats if s.get("seatNumber") == self_seat_num), {})
        hole = list(self_seat.get("holeCards") or [])
        board = list(table.get("boardCards") or [])

        if len(hole) != 2:
            result = self._deadline_action(table)
            self._record_timing(t0)
            return result

        pot = int(table.get("potChips") or 0)
        call_chips = int(allowed.get("callChips") or 0)
        big_blind = int(table.get("bigBlindChips") or 2)

        # Calculate effective stack
        my_stack = int(self_seat.get("stackChips") or 0)
        active_opponent_stacks = [
            int(s.get("stackChips") or 0)
            for s in seats
            if s.get("seatNumber") != self_seat_num and (s.get("stackChips") or 0) > 0
        ]
        effective_stack = min(my_stack, min(active_opponent_stacks)) if active_opponent_stacks else my_stack
        stack_depth_bb = effective_stack / max(big_blind, 1)
        n_players = len([s for s in seats if (s.get("stackChips") or 0) > 0])

        # Position — use table override if provided (stress test passes actual position)
        self_position = table.get("selfPosition") or seat_to_position(self_seat_num, n_players)

        # Determine street
        street = table.get("street") or "Preflop"
        if not board:
            street = "Preflop"
        elif len(board) == 3:
            street = "Flop"
        elif len(board) == 4:
            street = "Turn"
        else:
            street = "River"

        # Determine if we're the aggressor
        is_aggressor = self._determine_aggressor(table, self_position, street)

        # ─── Opponent context ──────────────────────────────────────
        opponent_archetypes: dict[str, str] = {}
        fold_to_cbet_data: dict[str, str] = {}
        for s in seats:
            sid = s.get("agentId", "")
            snum = str(s.get("seatNumber", ""))
            if sid and s.get("seatNumber") != self_seat_num:
                arch = self.opponent_model.get_archetype(sid)
                fcb = self.opponent_model.get_fold_to_cbet(sid)
                if arch != "Unknown":
                    opponent_archetypes[snum] = arch
                if fcb != "unknown":
                    fold_to_cbet_data[snum] = fcb

        # ─── Pool classification ──────────────────────────────────
        opponent_bot_types = table.get("opponentBotTypes") or {}
        strategy_mode, pool = classify_and_select(
            opponent_archetypes=opponent_archetypes,
            opponent_bot_types=opponent_bot_types,
            self_position=self_position,
            stack_depth_bb=stack_depth_bb,
        )
        global _active_strategy_mode, _active_pool_classification, _active_strategy_weights
        _active_strategy_mode = strategy_mode
        _active_pool_classification = {
            "pool_type": pool.pool_type,
            "confidence": pool.confidence,
            "reasoning": pool.reasoning,
            "opponent_types": pool.opponent_types,
            "passive_count": pool.passive_count,
            "aggressive_count": pool.aggressive_count,
        }

        # ─── Continuous strategy mixing (replaces hard routing) ─────
        try:
            # Estimate hand strength for weight computation
            hand_strength = self._estimate_hand_strength(hole, board, street)

            # Compute pot-to-stack ratio
            pot_to_stack = pot / max(effective_stack, 1)

            # Estimate table aggression from opponent data
            table_aggression = 0.5
            if pool.pool_type == "aggressive":
                table_aggression = 0.75
            elif pool.pool_type == "passive":
                table_aggression = 0.25

            # Contextual weights (Task 2)
            raw_weights = self.mixer.compute_weights(
                pool_type=pool.pool_type,
                confidence=pool.confidence,
                position=self_position,
                stack_depth_bb=stack_depth_bb,
                hand_strength=hand_strength,
                street=street,
                pot_to_stack=pot_to_stack,
                table_aggression=table_aggression,
            )

            # Smooth transition (Task 3)
            weights = self.mixer.smooth_weights(raw_weights, pool.pool_type, pool.confidence)
            _active_strategy_weights = dict(weights)
            _active_strategy_mode = max(weights, key=weights.get)

            # Task 4: aggressive matchup fix — blend raise_exploit with limp_value
            if pool.pool_type == "aggressive" and hand_strength < 0.65:
                weights = self._aggressive_blend(weights)

            # Run all three strategies
            votes = self._run_all_strategies(
                hole, table, board, street, self_position,
                opponent_archetypes, stack_depth_bb, is_aggressor,
            )

            # Blend (Task 1)
            blended = self.mixer.blend(votes, weights)

        except Exception:
            # Any strategy exception → fallback to safe action
            result = self._safe_fallback(allowed, available, pot, call_chips)
            self._record_timing(t0)
            return result

        # ─── Validate and build result ─────────────────────────────
        result = self._validate_and_build_blended(
            blended, allowed, available, table, hole, board, street, self_position
        )
        self._record_timing(t0)
        return result

    def _estimate_hand_strength(self, hole: list[str], board: list[str],
                                 street: str) -> float:
        """Quick hand strength estimate for weight computation (0.0-1.0)."""
        if not board:
            # Preflop: use simple heuristic
            from ..strategy.limp_value import _preflop_strength
            return _preflop_strength(hole)
        from ..strategy.limp_value import _postflop_strength
        return _postflop_strength(hole, board)

    def _run_all_strategies(
        self, hole: list[str], table: dict, board: list[str],
        street: str, self_position: str,
        opponent_archetypes: dict[str, str],
        stack_depth_bb: float, is_aggressor: bool,
    ) -> list[StrategyVote]:
        """Run all three strategies and return their votes."""
        votes: list[StrategyVote] = []

        # ── Limp-Value ──────────────────────────────────────────
        try:
            from ..strategy.limp_value import (
                decide_preflop_limp_value, decide_flop_limp_value,
                decide_turn_limp_value, decide_river_limp_value,
            )
            if street == "Preflop":
                lv = decide_preflop_limp_value(hole, table, opponent_archetypes, stack_depth_bb, self_position)
            elif street == "Flop":
                lv = decide_flop_limp_value(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            elif street == "Turn":
                lv = decide_turn_limp_value(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            else:
                lv = decide_river_limp_value(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            votes.append(StrategyVote(lv.action, lv.amount, lv.confidence, lv.reasoning, "limp_value"))
        except Exception:
            votes.append(StrategyVote("fold", None, 0.0, "limp_value error", "limp_value"))

        # ── Raise-Exploit ───────────────────────────────────────
        try:
            from ..strategy.preflop import decide_preflop
            from ..strategy.flop import decide_flop
            from ..strategy.turn import decide_turn
            from ..strategy.river import decide_river
            if street == "Preflop":
                re = decide_preflop(hole, table, opponent_archetypes, stack_depth_bb, self_position)
            elif street == "Flop":
                re = decide_flop(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            elif street == "Turn":
                re = decide_turn(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            else:
                re = decide_river(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            votes.append(StrategyVote(re.action, re.amount, re.confidence, re.reasoning, "raise_exploit"))
        except Exception:
            votes.append(StrategyVote("fold", None, 0.0, "raise_exploit error", "raise_exploit"))

        # ── Hybrid ──────────────────────────────────────────────
        try:
            from ..strategy.hybrid import (
                decide_preflop_hybrid, decide_flop_hybrid,
                decide_turn_hybrid, decide_river_hybrid,
            )
            if street == "Preflop":
                hy = decide_preflop_hybrid(hole, table, opponent_archetypes, stack_depth_bb, self_position)
            elif street == "Flop":
                hy = decide_flop_hybrid(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            elif street == "Turn":
                hy = decide_turn_hybrid(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            else:
                hy = decide_river_hybrid(hole, table, opponent_archetypes, stack_depth_bb, self_position, is_aggressor)
            votes.append(StrategyVote(hy.action, hy.amount, hy.confidence, hy.reasoning, "hybrid"))
        except Exception:
            votes.append(StrategyVote("fold", None, 0.0, "hybrid error", "hybrid"))

        return votes

    def _aggressive_blend(self, weights: dict[str, float]) -> dict[str, float]:
        """Task 4: Blend raise_exploit with limp_value vs aggressive opponents.

        Against LAG/Maniac, pure aggression feeds their strategy.
        Blending toward limp_value increases trap frequency — call their
        bluffs, don't build pots they can steal.
        """
        w = dict(weights)
        # Shift 30% of raise_exploit weight → limp_value
        shift = w["raise_exploit"] * 0.30
        w["raise_exploit"] -= shift
        w["limp_value"] += shift
        # Normalize
        total = sum(w.values())
        return {k: v / total for k, v in w.items()}

    def _validate_and_build_blended(
        self, blended: BlendedDecision,
        allowed: dict, available: list,
        table: dict, hole: list[str], board: list[str],
        street: str, position: str,
    ) -> dict:
        """Validate the blended decision and build Arena response with explainer log."""
        action_name = blended.action
        amount = blended.amount

        # Check if action is in available actions (same fallback logic)
        if action_name not in available:
            alternatives = {
                "bet": ["raise", "call", "check", "fold"],
                "raise": ["bet", "call", "check", "fold"],
                "call": ["check", "fold"],
                "check": ["fold"],
                "fold": ["check"],
                "all-in": ["raise", "bet", "call", "check", "fold"],
            }
            for alt in alternatives.get(action_name, ["fold"]):
                if alt in available:
                    action_name = alt
                    if alt in ("check", "fold"):
                        amount = None
                    break
            else:
                action_name = "fold"
                amount = None

        # Validate amount for bet/raise
        if action_name in ("bet", "raise"):
            br = allowed.get("betRange") or allowed.get("raiseRange") or {}
            lo = int(br.get("min") or 1)
            hi = int(br.get("max") or 999999)
            if amount is None:
                amount = lo
            amount = max(lo, min(int(amount), hi))

        if action_name in ("fold", "check", "call"):
            amount = None
        if action_name == "all-in":
            amount = None

        # Build reasoning with explainer log (Task 5)
        reasoning = self._build_reasoning_blended(
            action_name, blended, hole, board, street, position
        )

        payload: dict = {
            "action": action_name,
            "message": blended.reasoning[:500],
            "reasoning": reasoning,
            # Strategy explainer log (Task 5)
            "strategy_weights": blended.weights_used,
            "strategy_votes": blended.votes,
            "blend_method": blended.blend_method,
        }
        if amount is not None:
            payload["amount"] = int(amount)

        return payload

    def _build_reasoning_blended(
        self, action_name: str, blended: BlendedDecision,
        hole: list[str], board: list[str], street: str, position: str,
    ) -> str:
        """Build Arena-compliant reasoning string with blend info (≤150 chars)."""
        cls = hand_class(hole) if hole else "??"

        # Board features
        if not board:
            bf_str = "[]"
        else:
            suits = [c[-1].lower() for c in board if len(c) >= 2]
            feats = []
            for s in set(suits):
                if suits.count(s) >= 2:
                    feats.append(f"FD-{s}")
            ranks_list = [c[0].upper() for c in board]
            if len(set(ranks_list)) < len(ranks_list):
                feats.append("paired")
            bf_str = "[" + ",".join(feats[:3]) + "]" if feats else "[dry]"

        # Key equity
        eq = static_preflop_equity(hole) if not board else 0.5
        ke_str = f"{int(eq * 100)}% eq"[:30]

        # Position plan
        pos_abbr = "IP" if position in ("BTN", "CO") else "OOP"
        plan_map = {"Preflop": "see flop", "Flop": "barrel T",
                    "Turn": "ck R", "River": "showdown"}
        pp_str = f"{pos_abbr} {plan_map.get(street, 'pot ctrl')}"[:30]

        # Blend signature: dominant strategy + method
        dominant = max(blended.weights_used, key=blended.weights_used.get)
        blend_tag = f"mx:{dominant[:4]}"[:8]

        parts = [
            f'vr: "ln:{position.lower()}"',
            f'ke: "{ke_str}"',
            f'bf: {bf_str}',
            f'pp: "{pp_str}"',
            f'{blend_tag}',
        ]
        if blended.blend_method != "majority":
            parts.append(f"how:{blended.blend_method[:6]}")

        yaml = "{" + ", ".join(parts) + "}"
        if len(yaml) <= 150:
            return yaml

        for drop_i in (5, 4, 2):
            if drop_i < len(parts):
                trimmed = parts[:drop_i] + parts[drop_i + 1:]
                candidate = "{" + ", ".join(trimmed) + "}"
                if len(candidate) <= 150:
                    return candidate
        return FALLBACK_REASONING

    def _determine_aggressor(self, table: dict, position: str, street: str) -> bool:
        """Heuristic: are we the preflop raiser (and thus the natural c-bettor)?

        Uses explicit flag from simulation if available, otherwise estimates
        from action context.
        """
        if street == "Preflop":
            return False

        # Check explicit flag from simulation
        allowed = table.get("allowedActions") or {}
        if allowed.get("heroRaisedPreflop"):
            return True

        call_chips = allowed.get("callChips", 0)
        # In position (BTN/CO) facing no bet → likely our initiative
        if call_chips == 0 and allowed.get("canBet", False) and position in ("BTN", "CO"):
            return True
        # In position facing a donk bet → we still have initiative
        if allowed.get("canRaise", False) and position in ("BTN", "CO"):
            return True
        # Out of position with chance to bet → may have initiative (check)
        if call_chips == 0 and allowed.get("canBet", False):
            return True
        # Facing a bet out of position → opponent has initiative
        if allowed.get("canRaise", False):
            return False
        return False

    def _deadline_action(self, table: dict) -> dict:
        """Emergency action when deadline is too tight."""
        allowed = table.get("allowedActions") or {}
        if allowed.get("canCheck"):
            return {"action": "check", "message": "deadline tight",
                    "reasoning": FALLBACK_REASONING}
        return {"action": "fold", "message": "deadline tight",
                "reasoning": FALLBACK_REASONING}

    def _safe_fallback(self, allowed: dict, available: list,
                       pot: int, call_chips: int) -> dict:
        """Fallback action when strategy fails."""
        if "check" in available:
            return {"action": "check", "message": "safe fallback",
                    "reasoning": FALLBACK_REASONING}
        if call_chips == 0 and "call" in available:
            return {"action": "call", "message": "safe fallback",
                    "reasoning": FALLBACK_REASONING}
        if "fold" in available:
            return {"action": "fold", "message": "safe fallback",
                    "reasoning": FALLBACK_REASONING}
        return {"action": "fold", "message": "emergency fold",
                "reasoning": FALLBACK_REASONING}

    def _record_timing(self, t0: float) -> None:
        elapsed = (time.perf_counter() - t0) * 1000
        self.decision_count += 1
        self.total_decision_time_ms += elapsed

    @property
    def avg_decision_time_ms(self) -> float:
        if self.decision_count == 0:
            return 0.0
        return self.total_decision_time_ms / self.decision_count

    def get_stats(self) -> dict:
        return {
            "decisions": self.decision_count,
            "avg_time_ms": round(self.avg_decision_time_ms, 1),
            "total_time_ms": round(self.total_decision_time_ms, 1),
        }
