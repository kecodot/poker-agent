"""Decision engine — combines all modules into a single decision pipeline.

The decision engine:
  1. Extracts game state from the table dict
  2. Identifies relevant context (position, stacks, opponents)
  3. Routes to the appropriate street strategy
  4. Validates the action against allowed actions
  5. Generates Arena-compliant reasoning

This is the single entry point that decide() calls.
"""

from __future__ import annotations

import random
import time
from typing import Optional

from ..engine.hand_evaluator import _hand_class, static_preflop_equity
from ..engine.equity_calculator import compute_full_equity, compute_pot_odds
from ..engine.range_engine import seat_to_position, hand_class
from ..engine.opponent_model import OpponentModel
from ..strategy.preflop import decide_preflop, PreflopDecision
from ..strategy.flop import decide_flop, FlopDecision, _board_texture
from ..strategy.turn import decide_turn, TurnDecision
from ..strategy.river import decide_river, RiverDecision

FALLBACK_REASONING = '{vr: "std", ke: "legal", pp: "pot control"}'


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

        # Position
        self_position = seat_to_position(self_seat_num, n_players)

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

        # ─── Delegate to street strategy ───────────────────────────
        try:
            if street == "Preflop":
                decision = decide_preflop(
                    hole=hole,
                    table=table,
                    opponent_archetypes=opponent_archetypes,
                    stack_depth_bb=stack_depth_bb,
                    self_position=self_position,
                )
            elif street == "Flop":
                decision = decide_flop(
                    hole=hole,
                    table=table,
                    opponent_archetypes=opponent_archetypes,
                    stack_depth_bb=stack_depth_bb,
                    self_position=self_position,
                    is_aggressor=is_aggressor,
                )
            elif street == "Turn":
                decision = decide_turn(
                    hole=hole,
                    table=table,
                    opponent_archetypes=opponent_archetypes,
                    stack_depth_bb=stack_depth_bb,
                    self_position=self_position,
                    is_aggressor=is_aggressor,
                )
            else:  # River
                decision = decide_river(
                    hole=hole,
                    table=table,
                    opponent_archetypes=opponent_archetypes,
                    stack_depth_bb=stack_depth_bb,
                    self_position=self_position,
                    is_aggressor=is_aggressor,
                )
        except Exception:
            # Any strategy exception → fallback to safe action
            result = self._safe_fallback(allowed, available, pot, call_chips)
            self._record_timing(t0)
            return result

        # ─── Validate and build result ─────────────────────────────
        result = self._validate_and_build(
            decision, allowed, available, table, hole, board, street, self_position
        )
        self._record_timing(t0)
        return result

    def _determine_aggressor(self, table: dict, position: str, street: str) -> bool:
        """Heuristic: are we the preflop raiser (and thus the natural c-bettor)?

        We can't see opponent hole cards, but we can estimate from action context.
        """
        if street == "Preflop":
            return False
        allowed = table.get("allowedActions") or {}
        call_chips = allowed.get("callChips", 0)
        # If no one bet and we can bet → we likely have initiative
        if call_chips == 0 and allowed.get("canBet", False):
            return True
        # If we can raise → someone else bet, they have initiative
        if allowed.get("canRaise", False):
            return False
        return False

    def _validate_and_build(
        self,
        decision,
        allowed: dict,
        available: list,
        table: dict,
        hole: list[str],
        board: list[str],
        street: str,
        position: str,
    ) -> dict:
        """Validate the strategy decision against allowed actions and build Arena response."""
        action_name = decision.action
        amount = decision.amount

        # Check if action is in available actions
        if action_name not in available:
            # Map common alternatives
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

        # Strip amount for fold/check/call
        if action_name in ("fold", "check", "call"):
            amount = None
        if action_name == "all-in":
            amount = None  # Server handles all-in sizing

        # Build reasoning
        reasoning = self._build_reasoning(
            action_name, decision, hole, board, street, position
        )

        payload: dict = {
            "action": action_name,
            "message": decision.reasoning[:500],
            "reasoning": reasoning,
        }
        if amount is not None:
            payload["amount"] = int(amount)

        return payload

    def _build_reasoning(
        self,
        action_name: str,
        decision,
        hole: list[str],
        board: list[str],
        street: str,
        position: str,
    ) -> str:
        """Build Arena-compliant YAML flow-style reasoning string (≤150 chars)."""
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

        # Sizing reason
        sr_str = ""
        if action_name in ("bet", "raise", "all-in"):
            sr_str = "sized for FE"[:30]
        elif action_name == "call":
            sr_str = "covered"[:30]

        parts = [
            f'vr: "ln:{position.lower()}"',
            f'ke: "{ke_str}"',
            f'bf: {bf_str}',
            f'pp: "{pp_str}"',
        ]
        if sr_str:
            parts.append(f'sr: "{sr_str}"')

        yaml = "{" + ", ".join(parts) + "}"
        if len(yaml) <= 150:
            return yaml

        # Trim to fit
        for drop_i in (4, 2):
            if drop_i < len(parts):
                trimmed = parts[:drop_i] + parts[drop_i + 1:]
                candidate = "{" + ", ".join(trimmed) + "}"
                if len(candidate) <= 150:
                    return candidate
        return FALLBACK_REASONING

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
