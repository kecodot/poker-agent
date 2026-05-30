"""Hybrid Strategy — balanced between limp-value and raise-exploit.

Used for mixed opponent pools where we can't clearly classify as
passive or aggressive. Raises premiums, limps playable, folds trash.
Postflop: value-bets strong, calls down reasonably, bluffs selectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine.range_engine import (
    hand_class,
    is_in_opening_range,
    is_premium,
    is_strong,
)
from .limp_value import _preflop_strength, _postflop_strength


@dataclass
class HybridDecision:
    action: str
    amount: Optional[int]
    reasoning: str
    confidence: float


def decide_preflop_hybrid(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
) -> HybridDecision:
    """Hybrid preflop: raise strong, limp playable, fold trash.

    Combines the best of both worlds:
    - Builds pots with premium holdings
    - Sees cheap flops with speculative hands
    - Avoids investing in trash
    """
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    big_blind = int(table.get("bigBlindChips") or 2)
    rr = allowed.get("raiseRange") or {}
    raise_min = int(rr.get("min") or big_blind * 2)
    raise_max = int(rr.get("max") or 999999)
    strength = _preflop_strength(hole)
    cls = hand_class(hole)

    if call_chips == 0:
        # Unopened pot
        # Premium hands: raise (like raise_exploit)
        if is_in_opening_range(hole, self_position, 2) and "raise" in available:
            size = min(raise_max, max(raise_min, int(big_blind * 2.5)))
            return HybridDecision("raise", size,
                f"hybrid: raise {cls} from {self_position}", 0.8)

        # Playable hands: limp (like limp_value)
        if strength > 0.35 and "call" in available:
            return HybridDecision("call", None,
                f"hybrid: limp {cls} from {self_position}", 0.5)

        # BB check option
        if "check" in available:
            return HybridDecision("check", None,
                f"hybrid: check BB option {cls}", 0.7)

        return HybridDecision("fold", None,
            f"hybrid: fold {cls} from {self_position}", 0.8)
    else:
        # Facing a bet/raise
        if self_position == "BB":
            # BB defense: call with playable, raise with premiums
            if is_premium(hole) and "raise" in available:
                size = min(raise_max, max(raise_min, call_chips * 3))
                return HybridDecision("raise", size,
                    f"hybrid: 3bet premium {cls} from BB", 0.85)
            if strength > 0.40 and "call" in available:
                return HybridDecision("call", None,
                    f"hybrid: BB defend {cls}", 0.5)

        # In position: call with playable
        if self_position in ("BTN", "CO"):
            if is_strong(hole) and "raise" in available:
                size = min(raise_max, max(raise_min, call_chips * 3))
                return HybridDecision("raise", size,
                    f"hybrid: 3bet {cls} IP", 0.8)
            if strength > 0.42 and "call" in available:
                return HybridDecision("call", None,
                    f"hybrid: IP call {cls}", 0.5)

        if "check" in available:
            return HybridDecision("check", None, "hybrid: check option", 0.6)
        return HybridDecision("fold", None,
            f"hybrid: fold {cls} to bet", 0.8)


def decide_flop_hybrid(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> HybridDecision:
    """Hybrid flop: value bet strong, call down with pair/draw, selective bluffs."""
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    board = list(table.get("boardCards") or [])
    strength = _postflop_strength(hole, board)

    if call_chips == 0:
        # Value bet strong hands, check rest
        if strength > 0.65 and "bet" in available:
            return HybridDecision("bet", pot // 2,
                f"hybrid: value bet {strength:.0%}", 0.75)
        # Aggressor semi-bluff with draws
        if is_aggressor and strength > 0.45 and "bet" in available:
            import random
            if random.random() < 0.30:
                return HybridDecision("bet", pot // 3,
                    f"hybrid: semi-bluff {strength:.0%}", 0.5)
        if "check" in available:
            return HybridDecision("check", None, "hybrid: check flop", 0.7)
        return HybridDecision("fold", None, "no free option", 0.5)
    else:
        # Strong → raise
        if strength > 0.70 and "raise" in available:
            return HybridDecision("raise", call_chips * 3,
                f"hybrid: raise {strength:.0%}", 0.8)
        # Any piece → call
        if strength > 0.35 and "call" in available and call_chips <= pot * 0.7:
            return HybridDecision("call", None,
                f"hybrid: call {strength:.0%}", 0.45)
        if "check" in available:
            return HybridDecision("check", None, "hybrid: free option", 0.6)
        return HybridDecision("fold", None,
            f"hybrid: fold {strength:.0%}", 0.7)


def decide_turn_hybrid(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> HybridDecision:
    """Hybrid turn: continuation of flop strategy."""
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    board = list(table.get("boardCards") or [])
    strength = _postflop_strength(hole, board)

    if call_chips == 0:
        if strength > 0.65 and "bet" in available:
            return HybridDecision("bet", pot // 2,
                f"hybrid: turn value bet {strength:.0%}", 0.75)
        if "check" in available:
            return HybridDecision("check", None, "hybrid: check turn", 0.7)
        return HybridDecision("fold", None, "no free option", 0.5)
    else:
        if strength > 0.70 and "raise" in available:
            return HybridDecision("raise", call_chips * 2,
                f"hybrid: turn raise {strength:.0%}", 0.8)
        if strength > 0.35 and "call" in available and call_chips <= pot * 0.6:
            return HybridDecision("call", None,
                f"hybrid: turn call {strength:.0%}", 0.4)
        if "check" in available:
            return HybridDecision("check", None, "hybrid: free turn", 0.6)
        return HybridDecision("fold", None,
            f"hybrid: turn fold {strength:.0%}", 0.7)


def decide_river_hybrid(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> HybridDecision:
    """Hybrid river: value-heavy, thin calls when price is right."""
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    board = list(table.get("boardCards") or [])
    strength = _postflop_strength(hole, board)

    if call_chips == 0:
        if strength > 0.55 and "bet" in available:
            return HybridDecision("bet", pot // 2,
                f"hybrid: river value {strength:.0%}", 0.75)
        if "check" in available:
            return HybridDecision("check", None, "hybrid: check river", 0.7)
        return HybridDecision("fold", None, "no free option", 0.5)
    else:
        if strength > 0.60 and "raise" in available:
            return HybridDecision("raise", call_chips * 2,
                f"hybrid: river raise {strength:.0%}", 0.8)
        if strength > 0.40 and "call" in available and call_chips <= pot * 0.5:
            return HybridDecision("call", None,
                f"hybrid: river call {strength:.0%}", 0.4)
        if "check" in available:
            return HybridDecision("check", None, "hybrid: free river", 0.6)
        return HybridDecision("fold", None,
            f"hybrid: river fold {strength:.0%}", 0.7)
