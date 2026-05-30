"""Complete preflop strategy — position-aware, stack-depth-aware.

Handles all preflop decisions:
  - Open raising from each position
  - Facing opens (call/3bet/fold)
  - Facing 3-bets (call/4bet/fold/5bet-ALLIN)
  - Blind defense
  - Limping and facing limps
  - Short stack adjustments (< 20BB, < 40BB)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine.range_engine import (
    hand_class,
    seat_to_position,
    is_in_opening_range,
    is_in_3bet_range,
    is_in_4bet_range,
    is_5bet_all_in,
    is_in_defend_range,
    is_in_sb_open,
    is_premium,
    is_strong,
    is_playable,
    OPENING_RANGES,
    THREE_BET_RANGES,
    FOUR_BET_RANGES,
    FIVE_BET_ALL_IN,
    DEFEND_VS_OPEN,
    SB_VS_BB_OPEN,
    BB_VS_SB_3BET,
)
from ..engine.hand_evaluator import static_preflop_equity


@dataclass
class PreflopDecision:
    action: str            # fold, call, raise, all-in
    amount: Optional[int]  # raise size in chips (total committed)
    reasoning: str         # short explanation
    confidence: float      # 0.0-1.0


def _raise_size(
    position: str,
    big_blind: int,
    pot: int,
    raise_min: int,
    raise_max: int,
    stack_depth_bb: float,
    is_isolation: bool = False,
) -> int:
    """Determine optimal preflop raise size based on position and stack depth.

    Returns total chips committed after the raise (not delta)."""
    bb = big_blind

    # Standard open sizes by position (in BB)
    if is_isolation:
        open_sizes = {"UTG": 3.0, "MP": 2.8, "CO": 2.5, "BTN": 2.3, "SB": 3.0, "BB": 3.0}
    else:
        open_sizes = {"UTG": 2.5, "MP": 2.5, "CO": 2.3, "BTN": 2.0, "SB": 3.0, "BB": 3.0}

    # Adjust for short stacks
    mult = open_sizes.get(position, 2.5)
    if stack_depth_bb < 30:
        mult = min(mult, 2.2)  # Smaller opens when short
    if stack_depth_bb < 15:
        mult = min(mult, 2.0)

    target = int(bb * mult)
    # Clamp to allowed range
    target = max(raise_min, min(target, raise_max))
    return target


def _three_bet_size(
    position: str,
    original_raise: int,
    big_blind: int,
    raise_min: int,
    raise_max: int,
    stack_depth_bb: float,
    is_blind: bool = False,
) -> int:
    """Determine 3-bet sizing.

    Standard: 3x the original raise in position, 4x out of position."""
    mult = 4.0 if is_blind else 3.0
    if stack_depth_bb < 30:
        mult = 3.0 if is_blind else 2.5

    target = int(original_raise * mult)
    if target < big_blind * 5:
        target = big_blind * 5

    target = max(raise_min, min(target, raise_max))
    return target


def _facing_action_type(table: dict) -> str:
    """Determine what action we're facing preflop.

    Returns: 'unopened' | 'facing_open' | 'facing_3bet' | 'facing_4bet' | 'facing_limp'
    """
    allowed = table.get("allowedActions") or {}
    call_chips = allowed.get("callChips", 0)

    if call_chips == 0 and allowed.get("canBet", False):
        return "unopened"
    if call_chips == 0:
        return "facing_limp"

    # Estimate number of raises so far by the size relative to BB
    bb = int(table.get("bigBlindChips", 2))
    pot = int(table.get("potChips", 0))

    if call_chips <= bb + 2:
        return "facing_limp"
    if call_chips <= bb * 6:
        return "facing_open"
    if call_chips <= bb * 20:
        return "facing_3bet"
    return "facing_4bet"


def decide_preflop(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
) -> PreflopDecision:
    """Main preflop decision function.

    Args:
        hole: Hero's hole cards
        table: Arena table dict
        opponent_archetypes: Map of seat → archetype
        stack_depth_bb: Effective stack in BB
        self_position: Hero's position label
    """
    if opponent_archetypes is None:
        opponent_archetypes = {}

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = int(table.get("potChips") or 0)
    big_blind = int(table.get("bigBlindChips") or 2)
    small_blind = int(table.get("smallBlindChips") or 1)
    self_seat = table.get("selfSeatNumber") or 0
    n_players = len(table.get("seats") or [])

    if not self_position:
        self_position = seat_to_position(self_seat, n_players)

    cls = hand_class(hole)
    equity = static_preflop_equity(hole)
    action_type = _facing_action_type(table)

    rr = allowed.get("raiseRange") or allowed.get("betRange") or {}
    raise_min = int(rr.get("min") or big_blind * 2)
    raise_max = int(rr.get("max") or 999999)

    # ─── Short stack logic ─────────────────────────────────────────
    if stack_depth_bb < 10:
        if is_strong(hole) or equity > 0.6:
            if "all-in" in available:
                return PreflopDecision("all-in", None,
                    f"short stack ({stack_depth_bb:.0f}BB), {cls} all-in",
                    min(equity, 0.95))
            if "raise" in available:
                return PreflopDecision("raise", raise_max,
                    f"short stack ({stack_depth_bb:.0f}BB), {cls} committed",
                    min(equity, 0.9))
            if "call" in available:
                return PreflopDecision("call", None,
                    f"short stack call {cls}", equity - 0.05)
        if call_chips == 0 and "check" in available:
            return PreflopDecision("check", None,
                f"short stack free flop {cls}", 0.3)
        return PreflopDecision("fold", None,
            f"short stack fold {cls}", 0.8)

    # ─── Unopened pot ──────────────────────────────────────────────
    if action_type == "unopened":
        if is_in_opening_range(hole, self_position):
            size = _raise_size(self_position, big_blind, pot, raise_min, raise_max, stack_depth_bb)
            action = "raise" if "raise" in available else "bet"
            if action in available:
                return PreflopDecision(action, size,
                    f"open {cls} from {self_position} to {size} chips",
                    0.85)
            if "call" in available:
                return PreflopDecision("call", None,
                    f"open {cls} from {self_position} (call fallback)", 0.5)

        # Late position steals
        if self_position in ("BTN", "CO") and stack_depth_bb > 40:
            if is_playable(hole, self_position) and equity > 0.45:
                if "raise" in available or "bet" in available:
                    action = "raise" if "raise" in available else "bet"
                    size = _raise_size(self_position, big_blind, pot,
                                       raise_min, raise_max, stack_depth_bb, is_isolation=True)
                    return PreflopDecision(action, size,
                        f"steal attempt {cls} from {self_position}", 0.6)
            if call_chips == 0 and "check" in available:
                return PreflopDecision("check", None,
                    f"limp {cls} from {self_position}", 0.3)

        # SB special case
        if self_position == "SB" and call_chips == 0:
            if is_in_sb_open(hole) and ("raise" in available or "bet" in available):
                action = "raise" if "raise" in available else "bet"
                size = _raise_size(self_position, big_blind, pot, raise_min, raise_max, stack_depth_bb)
                return PreflopDecision(action, size,
                    f"SB steal {cls}", 0.7)
            if "call" in available and is_playable(hole, "SB"):
                return PreflopDecision("call", None,
                    f"SB complete {cls}", 0.35)

        if "check" in available:
            return PreflopDecision("check", None, f"fold {cls} (free option)", 0.9)
        return PreflopDecision("fold", None,
            f"{cls} not in {self_position} opening range", 0.9)

    # ─── Facing an open ────────────────────────────────────────────
    if action_type == "facing_open":
        # 3-bet with strong hands
        if is_in_3bet_range(hole, self_position):
            size = _three_bet_size(self_position, call_chips, big_blind,
                                   raise_min, raise_max, stack_depth_bb,
                                   is_blind=self_position in ("SB", "BB"))
            if "raise" in available:
                return PreflopDecision("raise", size,
                    f"3bet {cls} from {self_position} to {size}", 0.85)
            if "all-in" in available and stack_depth_bb < 50:
                return PreflopDecision("all-in", None,
                    f"3bet all-in {cls} from {self_position}", equity)

        # Call with defend range (BB especially)
        if self_position in ("BB", "SB"):
            def_cls = BB_VS_SB_3BET if self_position == "BB" else is_in_defend_range
            if self_position == "BB" and cls in BB_VS_SB_3BET:
                if "call" in available:
                    return PreflopDecision("call", None,
                        f"defend BB with {cls}", equity - 0.05)
            elif self_position == "BB" and cls in DEFEND_VS_OPEN.get("vs_MP", set()):
                if "call" in available:
                    return PreflopDecision("call", None,
                        f"defend BB with {cls}", 0.5)

        # In position: call with playable hands
        if self_position in ("BTN", "CO"):
            if is_playable(hole, self_position):
                if "call" in available:
                    return PreflopDecision("call", None,
                        f"IP call {cls} from {self_position}", 0.55)
            if is_in_3bet_range(hole, self_position):
                size = _three_bet_size(self_position, call_chips, big_blind,
                                       raise_min, raise_max, stack_depth_bb)
                if "raise" in available:
                    return PreflopDecision("raise", size,
                        f"IP 3bet {cls} from {self_position}", 0.8)

        # Blind defense vs steals
        if self_position in ("BB",) and call_chips <= big_blind * 3:
            if equity > 0.35 and "call" in available:
                return PreflopDecision("call", None,
                    f"wide BB defend {cls}", 0.4)

        if "check" in available:
            return PreflopDecision("check", None, "free preflop", 0.9)
        return PreflopDecision("fold", None,
            f"{cls} not in defend/3bet range", 0.85)

    # ─── Facing a 3-bet ────────────────────────────────────────────
    if action_type == "facing_3bet":
        if is_in_4bet_range(hole, self_position):
            if "raise" in available and stack_depth_bb > 40:
                size = int(call_chips * 2.2)
                size = max(raise_min, min(size, raise_max))
                return PreflopDecision("raise", size,
                    f"4bet {cls} from {self_position} to {size}", 0.8)
            if "all-in" in available and stack_depth_bb < 50:
                return PreflopDecision("all-in", None,
                    f"4bet all-in {cls}", equity)

        # Call 3-bet in position
        if self_position in ("BTN", "CO") and is_strong(hole):
            if "call" in available and stack_depth_bb > 50:
                return PreflopDecision("call", None,
                    f"IP call 3bet {cls}", 0.5)

        # Fold to 3-bet (most hands fold here)
        if "check" in available:
            return PreflopDecision("check", None, "check option", 0.9)
        return PreflopDecision("fold", None,
            f"{cls} folds to 3bet", 0.85)

    # ─── Facing a 4-bet ────────────────────────────────────────────
    if action_type == "facing_4bet":
        if is_5bet_all_in(hole) and "all-in" in available:
            return PreflopDecision("all-in", None,
                f"5bet all-in {cls}", equity)
        if is_in_4bet_range(hole, self_position) and "all-in" in available:
            if stack_depth_bb < 50:
                return PreflopDecision("all-in", None,
                    f"all-in {cls} vs 4bet", equity)
        if "check" in available:
            return PreflopDecision("check", None, "check option", 0.9)
        if is_premium(hole) and "call" in available:
            return PreflopDecision("call", None,
                f"call 4bet with premium {cls}", 0.5)
        return PreflopDecision("fold", None,
            f"fold {cls} to 4bet", 0.9)

    # ─── Facing limps ──────────────────────────────────────────────
    if action_type == "facing_limp":
        if is_in_opening_range(hole, self_position):
            size = _raise_size(self_position, big_blind, pot, raise_min, raise_max,
                               stack_depth_bb, is_isolation=True)
            if "raise" in available:
                return PreflopDecision("raise", size,
                    f"iso-raise {cls} from {self_position} to {size}",
                    0.8)
            if "bet" in available:
                return PreflopDecision("bet", size,
                    f"iso-bet {cls} from {self_position} to {size}",
                    0.8)
        if is_playable(hole, self_position) and "call" in available:
            return PreflopDecision("call", None,
                f"overlimp {cls} from {self_position}", 0.4)
        if "check" in available:
            return PreflopDecision("check", None, f"check {cls} BB option", 0.7)
        return PreflopDecision("fold", None,
            f"fold {cls} vs limp (weak)", 0.7)

    # ─── Fallback ──────────────────────────────────────────────────
    if call_chips == 0:
        if "check" in available:
            return PreflopDecision("check", None, "fallback check", 0.5)
        return PreflopDecision("fold", None, "fallback fold", 0.5)
    if call_chips <= big_blind * 2 and "call" in available:
        return PreflopDecision("call", None, "small call", 0.4)
    return PreflopDecision("fold", None, "fallback fold", 0.7)
