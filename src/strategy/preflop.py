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
        open_sizes = {"UTG": 3.0, "MP": 2.8, "CO": 2.5, "BTN": 2.4, "SB": 3.0, "BB": 3.0}
    else:
        open_sizes = {"UTG": 2.5, "MP": 2.5, "CO": 2.5, "BTN": 2.2, "SB": 3.0, "BB": 3.0}

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

    # Explicit flag from simulation
    if allowed.get("isUnopened"):
        return "unopened"

    if call_chips == 0 and allowed.get("canBet", False):
        return "unopened"
    if call_chips == 0:
        return "facing_limp"

    # Estimate number of raises so far by the size relative to BB
    bb = int(table.get("bigBlindChips", 2))

    # First raise: open (up to ~6x BB)
    if call_chips <= bb * 6:
        return "facing_open"
    # Second raise: 3bet
    if call_chips <= bb * 20:
        return "facing_3bet"
    return "facing_4bet"


def _has_lag(opponent_archetypes: dict[str, str]) -> bool:
    """Check if any active opponent is classified as LAG or Maniac."""
    for seat, arch in opponent_archetypes.items():
        if arch in ("LAG", "Maniac"):
            return True
    return False


def _has_nit(opponent_archetypes: dict[str, str]) -> bool:
    """Check if any active opponent is classified as Nit."""
    return any(arch == "Nit" for arch in opponent_archetypes.values())


def decide_preflop(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
) -> PreflopDecision:
    """Main preflop decision function.

    Strategy: Raise-or-Fold from unopened pots (no limping).
    Adjusts 3bet frequencies and calling ranges vs LAG opponents.

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
    active_players = len([s for s in (table.get("seats") or []) if (s.get("stackChips") or 0) > 0])

    if not self_position:
        self_position = seat_to_position(self_seat, n_players)

    cls = hand_class(hole)
    equity = static_preflop_equity(hole)
    action_type = _facing_action_type(table)

    facing_lag = _has_lag(opponent_archetypes)
    facing_nit = _has_nit(opponent_archetypes)

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

    # ─── Unopened pot ───────────────────────────────────────────────
    if action_type == "unopened":
        # Open with standard range (RFI: Raise First In)
        # In HU, BTN/SB opens ~60% of hands. Fold bottom ~40%.
        # Every open risks 2.2 BB against calling stations that defend wide.
        # Folding costs 0.5 BB — better than opening trash and losing postflop.
        if is_in_opening_range(hole, self_position, active_players):
            size = _raise_size(self_position, big_blind, pot, raise_min, raise_max, stack_depth_bb)
            action = "raise" if "raise" in available else "bet"
            if action in available:
                return PreflopDecision(action, size,
                    f"open {cls} from {self_position} to {size} chips",
                    0.85)

        # SB: raise SB opening range, complete some playable hands
        if self_position == "SB" and call_chips == 0:
            if is_in_sb_open(hole) and ("raise" in available or "bet" in available):
                action = "raise" if "raise" in available else "bet"
                size = _raise_size(self_position, big_blind, pot, raise_min, raise_max, stack_depth_bb)
                return PreflopDecision(action, size,
                    f"SB raise {cls}", 0.7)
            # SB can complete with playable hands
            if "call" in available and is_playable(hole, "SB"):
                return PreflopDecision("call", None,
                    f"SB complete {cls}", 0.35)

        # BB: can check for free (doesn't count as VPIP)
        if "check" in available:
            return PreflopDecision("check", None, f"check {cls} (BB option)", 0.9)

        # Fold: hand not in opening range
        return PreflopDecision("fold", None,
            f"fold {cls} from {self_position}", 0.85)

        # Multi-way: Open with standard range (RFI: Raise First In)
        if is_in_opening_range(hole, self_position, active_players):
            size = _raise_size(self_position, big_blind, pot, raise_min, raise_max, stack_depth_bb)
            action = "raise" if "raise" in available else "bet"
            if action in available:
                return PreflopDecision(action, size,
                    f"open {cls} from {self_position} to {size} chips",
                    0.85)

        # SB: raise SB opening range, complete some playable hands
        if self_position == "SB" and call_chips == 0:
            if is_in_sb_open(hole) and ("raise" in available or "bet" in available):
                action = "raise" if "raise" in available else "bet"
                size = _raise_size(self_position, big_blind, pot, raise_min, raise_max, stack_depth_bb)
                return PreflopDecision(action, size,
                    f"SB raise {cls}", 0.7)
            # SB can complete with playable hands
            if "call" in available and is_playable(hole, "SB"):
                return PreflopDecision("call", None,
                    f"SB complete {cls}", 0.35)

        # BB: can check for free (doesn't count as VPIP)
        if "check" in available:
            return PreflopDecision("check", None, f"check {cls} (BB option)", 0.9)

        # Fold: hand not in opening range
        return PreflopDecision("fold", None,
            f"fold {cls} from {self_position}", 0.85)

    # ─── Facing an open ────────────────────────────────────────────
    if action_type == "facing_open":
        # Anti-LAG: widen 3bet range for value
        three_bet_range = is_in_3bet_range(hole, self_position)
        if facing_lag and not three_bet_range:
            if is_strong(hole) and self_position in ("BTN", "CO", "BB"):
                three_bet_range = True

        if three_bet_range:
            size = _three_bet_size(self_position, call_chips, big_blind,
                                   raise_min, raise_max, stack_depth_bb,
                                   is_blind=self_position in ("SB", "BB"))
            if "raise" in available:
                return PreflopDecision("raise", size,
                    f"3bet {cls} from {self_position} to {size}", 0.85)
            if "all-in" in available and stack_depth_bb < 50:
                return PreflopDecision("all-in", None,
                    f"3bet all-in {cls} from {self_position}", equity)

        # BB defense: use defend range or equity threshold
        if self_position == "BB":
            # Check vs_BTN defend range first
            if cls in DEFEND_VS_OPEN.get("vs_BTN", set()):
                if "call" in available:
                    return PreflopDecision("call", None,
                        f"defend BB {cls}", 0.55)
            # Equity-based defense: tighter threshold since static_preflop_equity
            # is vs random, not vs the opener's selected range
            if call_chips <= big_blind * 3:
                defend_eq = 0.40 if facing_lag else 0.45
                if equity > defend_eq and "call" in available:
                    return PreflopDecision("call", None,
                        f"BB defend {cls}", 0.4)

        # SB vs open
        if self_position == "SB":
            if cls in BB_VS_SB_3BET and "call" in available:
                return PreflopDecision("call", None,
                    f"SB call {cls}", 0.5)
            if equity > 0.50 and "call" in available and call_chips <= big_blind * 4:
                return PreflopDecision("call", None,
                    f"SB call {cls}", 0.4)

        # In position: call with playable hands (tighter vs LAG)
        if self_position in ("BTN", "CO"):
            if facing_lag:
                if is_strong(hole) and "call" in available:
                    return PreflopDecision("call", None,
                        f"IP call {cls} vs LAG", 0.55)
            elif is_playable(hole, self_position) and equity > 0.45:
                if "call" in available:
                    return PreflopDecision("call", None,
                        f"IP call {cls} from {self_position}", 0.55)

        if "check" in available:
            return PreflopDecision("check", None, "free preflop", 0.9)
        return PreflopDecision("fold", None,
            f"{cls} not in defend/3bet range", 0.85)

    # ─── Facing a 3-bet ────────────────────────────────────────────
    if action_type == "facing_3bet":
        # Vs LAG 3bet: trap with premiums (call instead of 4bet)
        if facing_lag and is_premium(hole) and self_position in ("BTN", "CO"):
            if "call" in available and stack_depth_bb > 40:
                return PreflopDecision("call", None,
                    f"trap {cls} vs LAG 3bet", 0.75)

        if is_in_4bet_range(hole, self_position):
            if "raise" in available and stack_depth_bb > 40:
                size = int(call_chips * 2.2)
                size = max(raise_min, min(size, raise_max))
                return PreflopDecision("raise", size,
                    f"4bet {cls} from {self_position} to {size}", 0.8)
            if "all-in" in available and stack_depth_bb < 50:
                return PreflopDecision("all-in", None,
                    f"4bet all-in {cls}", equity)

        # Call 3-bet in position with strong hands
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
        if is_in_opening_range(hole, self_position, active_players):
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
        # From blinds: check BB option, fold SB vs limps
        if self_position == "BB" and "check" in available and call_chips == 0:
            return PreflopDecision("check", None, f"check {cls} BB", 0.7)
        if self_position == "SB":
            if is_playable(hole, "SB") and "call" in available:
                return PreflopDecision("call", None,
                    f"SB complete {cls}", 0.35)
            return PreflopDecision("fold", None, f"fold {cls} SB vs limp", 0.75)
        # Iso-raise playable hands from LP
        if self_position in ("BTN", "CO") and is_playable(hole, self_position):
            if "raise" in available or "bet" in available:
                action = "raise" if "raise" in available else "bet"
                size = _raise_size(self_position, big_blind, pot, raise_min, raise_max,
                                   stack_depth_bb, is_isolation=True)
                return PreflopDecision(action, size,
                    f"iso {cls} from {self_position}", 0.55)
        return PreflopDecision("fold", None,
            f"fold {cls} vs limp", 0.7)

    # ─── Fallback ──────────────────────────────────────────────────
    if call_chips == 0:
        if "check" in available:
            return PreflopDecision("check", None, "fallback check", 0.5)
        return PreflopDecision("fold", None, "fallback fold", 0.5)
    if call_chips <= big_blind * 2 and "call" in available and self_position == "BB":
        return PreflopDecision("call", None, "BB small call", 0.4)
    return PreflopDecision("fold", None, "fallback fold", 0.7)
