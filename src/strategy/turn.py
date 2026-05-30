"""Turn strategy — evaluates drawn-out boards, barrel opportunities, and pot control.

Key differences from flop:
  - Higher bet sizing (50-75% pot)
  - Double barrel with equity + fold equity
  - Pot control with marginal made hands
  - Check-raise as a strong line
  - River planning (commitment decisions)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine.hand_evaluator import evaluate_hand, hand_strength_from_rank, hand_class_name
from ..engine.equity_calculator import compute_full_equity, compute_pot_odds
from ..engine.range_engine import seat_to_position
from ..strategy.flop import _board_texture, _flop_sizing, _hand_strength_by_board_interaction


@dataclass
class TurnDecision:
    action: str
    amount: Optional[int]
    reasoning: str
    confidence: float


def _get_spr_category(spr: float) -> str:
    """Categorize SPR for turn decisions."""
    if spr < 1.0:
        return "ultra_low"    # Pot committed
    if spr < 2.5:
        return "low"
    if spr < 6.0:
        return "medium"
    return "high"


def _can_commit(effective_stack: int, pot: int, equity: float, street: str) -> bool:
    """Determine if we can stack off with current hand."""
    spr = effective_stack / max(pot, 1)
    if spr <= 1.5 and equity > 0.30:
        return True
    if spr <= 3.0 and equity > 0.50:
        return True
    return equity > 0.75


def decide_turn(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> TurnDecision:
    """Main turn decision function."""
    if opponent_archetypes is None:
        opponent_archetypes = {}

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = int(table.get("potChips") or 0)
    board = list(table.get("boardCards") or [])
    big_blind = int(table.get("bigBlindChips") or 2)
    effective_stack = int(stack_depth_bb * big_blind)
    active_opponents = len([s for s in table.get("seats", [])
                           if s.get("stackChips", 0) > 0 and
                           s.get("seatNumber") != table.get("selfSeatNumber")])

    texture = _board_texture(board)
    interaction = _hand_strength_by_board_interaction(hole, board)

    # Equity with deadline
    equity_result = compute_full_equity(
        hole, board, pot, call_chips,
        effective_stack=effective_stack,
        n_opponents=active_opponents,
        street="Turn",
        deadline_ms=120,
    )

    spr = equity_result.spr
    spr_cat = _get_spr_category(spr)
    pot_odds = compute_pot_odds(call_chips, pot)
    sizing = _flop_sizing(texture, "turn")
    bet_size = int(pot * sizing)

    equity = equity_result.equity
    strength = interaction["strength"]
    hand_cls = interaction["hand_class"]

    # ─── Unopened ──────────────────────────────────────────────────
    if call_chips == 0:
        # Very strong → bet for value, plan to get it in
        if interaction["has_set"] or interaction["has_2pair"] or strength > 0.85:
            if "bet" in available:
                if _can_commit(effective_stack, pot, equity, "Turn"):
                    # Overbet or large bet to set up river shove
                    target = int(pot * 0.85) if spr < 3.0 else bet_size
                    return TurnDecision("bet", target,
                        f"barrel {hand_cls} on {texture} turn, setting up river", 0.92)
                return TurnDecision("bet", bet_size,
                    f"value bet {hand_cls} on turn", 0.88)

        # Top pair good kicker → value bet
        if (interaction["pair_type"] == "top" and strength > 0.65):
            if "bet" in available and spr_cat != "ultra_low":
                return TurnDecision("bet", bet_size,
                    f"value bet top pair on {texture} turn", 0.75)
            if is_aggressor and "bet" in available:
                return TurnDecision("bet", int(pot * sizing * 0.7),
                    f"double barrel top pair on {texture} turn", 0.68)

        # Draw that picked up equity → barrel
        if (interaction["has_draw"] and is_aggressor and
                "bet" in available):
            return TurnDecision("bet", int(pot * sizing * 0.75),
                f"semi-bluff barrel {interaction['draw_type']} on turn", 0.60)

        # Marginal made hand → pot control
        if interaction["has_pair"] and "check" in available:
            return TurnDecision("check", None,
                f"pot control {interaction['pair_type']} pair on turn", 0.65)

        # No equity, but can bluff
        if not interaction["has_pair"] and not interaction["has_draw"]:
            if is_aggressor and texture == "dry" and "bet" in available and spr > 5.0:
                # Double barrel bluff on dry board
                return TurnDecision("bet", int(pot * 0.55),
                    f"double barrel bluff on dry turn", 0.45)

        if "check" in available:
            return TurnDecision("check", None, "check turn", 0.7)
        return TurnDecision("fold", None, "no action available", 0.5)

    # ─── Facing a bet ──────────────────────────────────────────────

    # Strong → raise
    if interaction["has_set"] or interaction["has_2pair"]:
        if "raise" in available:
            rr = allowed.get("raiseRange") or {}
            r_min = int(rr.get("min") or call_chips * 2)
            r_max = int(rr.get("max") or r_min)
            raise_amt = max(r_min, min(int(call_chips * 2.8 + pot * 0.3), r_max))
            return TurnDecision("raise", raise_amt,
                f"raise {hand_cls} on turn, building pot", 0.90)
        if "call" in available:
            return TurnDecision("call", None,
                f"slowplay {hand_cls} on turn", 0.85)

    # Top pair → call reasonable bets
    if interaction["pair_type"] == "top":
        if equity >= pot_odds + 0.05 and "call" in available:
            if call_chips <= pot * 0.7:  # Don't call huge overbets
                return TurnDecision("call", None,
                    f"call top pair, {equity:.0%} vs {pot_odds:.0%}", 0.65)
        if "raise" in available and equity > 0.75:
            rr = allowed.get("raiseRange") or {}
            r_min = int(rr.get("min") or call_chips * 2)
            r_max = int(rr.get("max") or r_min)
            return TurnDecision("raise", max(r_min, int(call_chips * 2.3)),
                f"raise top pair for value on turn", 0.70)

    # Draws → evaluate implied odds
    if interaction["has_draw"]:
        if equity_result.has_implied_odds and "call" in available:
            if call_chips <= pot * 0.5:
                return TurnDecision("call", None,
                    f"draw {interaction['draw_type']}, implied odds on turn", 0.50)

    # SPR-based commitment decisions
    if spr_cat == "ultra_low":
        if strength > 0.30 and "call" in available:
            return TurnDecision("call", None, f"committed (SPR={spr:.1f})", 0.60)
        if "all-in" in available and strength > 0.45:
            return TurnDecision("all-in", None, f"commit with {hand_cls}", 0.70)
    elif spr_cat == "low":
        if strength > 0.55 and "call" in available:
            return TurnDecision("call", None, f"low SPR call", 0.60)
        if "raise" in available and strength > 0.70:
            rr = allowed.get("raiseRange") or {}
            return TurnDecision("raise", int(rr.get("min", call_chips * 2)),
                f"commit with {hand_cls}", 0.75)

    # General call
    if equity_result.has_direct_odds and "call" in available:
        return TurnDecision("call", None,
            f"call, {equity:.0%} eq vs {pot_odds:.0%}", 0.55)

    # Fold
    if "check" in available:
        return TurnDecision("check", None, "check option", 0.6)
    return TurnDecision("fold", None,
        f"fold on turn, {equity:.0%} eq vs {pot_odds:.0%} po", 0.78)
