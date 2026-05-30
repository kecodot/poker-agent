"""River strategy — showdown value assessment, thin value, and bluffing.

River is the most important street for bb/100.
Key concepts:
  - Value betting vs calling vs bluff catching
  - Polarized vs merged ranges
  - Block betting
  - Overbetting with the nuts
  - Hero calling with bluff catchers
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..engine.hand_evaluator import evaluate_hand, hand_strength_from_rank, hand_class_name
from ..engine.equity_calculator import compute_full_equity, compute_pot_odds
from ..engine.range_engine import seat_to_position
from ..engine.opponent_model import adjust_bluff_freq
from ..strategy.flop import _board_texture, _hand_strength_by_board_interaction


@dataclass
class RiverDecision:
    action: str
    amount: Optional[int]
    reasoning: str
    confidence: float


def _river_sizing(strength: float, pot: int, spr: float, texture: str) -> int:
    """Determine optimal river bet sizing.

    Nutted hands → overbet (1.2-2x pot)
    Strong value → 0.66-0.75x pot
    Thin value → 0.33-0.50x pot
    Bluff → 0.66-0.75x pot
    """
    if strength > 0.95:
        # Nuts — overbet
        if spr > 2.0:
            return int(pot * 1.5)
        return int(pot * 0.85)
    if strength > 0.80:
        return int(pot * 0.75)
    if strength > 0.60:
        return int(pot * 0.50)
    # Thin value / bluff sizing
    return int(pot * (0.66 if texture == "wet" else 0.50))


def _should_bluff_river(
    hole: list[str],
    board: list[str],
    interaction: dict,
    is_aggressor: bool,
    texture: str,
    pot: int,
    spr: float,
) -> bool:
    """Determine if we should bluff on the river.

    Good bluffs: missed draws, blockers to nuts, aggressive line."""
    if interaction["has_pair"] or interaction["strength"] > 0.55:
        return False

    # Missed draws make good bluffs
    if interaction["has_draw"]:
        return True

    # Aggressor who bet flop and turn
    if is_aggressor:
        return True

    # Blockers to the nuts
    ranks = "23456789TJQKA"
    board_ranks = [c[0].upper() for c in board]
    hole_ranks = [c[0].upper() for c in hole]
    high_cards = [r for r in hole_ranks if ranks.index(r) >= ranks.index("T")]
    if high_cards:
        return True

    return False


def _should_value_bet_river(
    interaction: dict,
    equity: float,
    texture: str,
) -> tuple[bool, str]:
    """Determine if we should value bet the river and what sizing category."""
    if interaction["has_set"]:
        return True, "thick"
    if interaction["has_2pair"]:
        return True, "thick"
    if interaction["pair_type"] == "top" and equity > 0.65:
        return True, "medium"
    if interaction["pair_type"] in ("middle", "bottom") and equity > 0.70:
        return True, "thin"
    if interaction["strength"] > 0.75:
        return True, "medium"
    return False, ""


def _is_bluff_catcher(interaction: dict, equity: float, pot_odds: float) -> bool:
    """Determine if our hand is a bluff catcher (beats bluffs, loses to value)."""
    if interaction["has_pair"] and interaction["pair_type"] in ("middle", "bottom", "top"):
        if equity < 0.50 and equity >= pot_odds - 0.05:
            return True
    if interaction["strength"] > 0.40 and interaction["strength"] < 0.60:
        if equity >= pot_odds - 0.03:
            return True
    return False


def decide_river(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> RiverDecision:
    """Main river decision function."""
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

    # Equity
    equity_result = compute_full_equity(
        hole, board, pot, call_chips,
        effective_stack=effective_stack,
        n_opponents=active_opponents,
        street="River",
        deadline_ms=100,
    )

    equity = equity_result.equity
    pot_odds = compute_pot_odds(call_chips, pot)
    spr = equity_result.spr
    strength = interaction["strength"]
    hand_cls = interaction["hand_class"]

    villain_archetype = list(opponent_archetypes.values())[0] if opponent_archetypes else "Unknown"

    # ─── Unopened (can check or bet) ───────────────────────────────
    if call_chips == 0:
        should_vbet, vbet_type = _should_value_bet_river(interaction, equity, texture)

        if should_vbet:
            if "bet" in available or "raise" in available:
                action = "bet" if "bet" in available else "raise"
                bet_amount = _river_sizing(strength, pot, spr, texture)
                br = allowed.get("betRange") or allowed.get("raiseRange") or {}
                lo = int(br.get("min") or 1)
                hi = int(br.get("max") or lo)
                bet_amount = max(lo, min(bet_amount, hi))
                return RiverDecision(action, bet_amount,
                    f"value bet {hand_cls} ({vbet_type}) on river", 0.92)

            # Can't bet/raise → call if it were available, else check
            if "check" in available:
                return RiverDecision("check", None,
                    f"check {hand_cls} (no bet available)", 0.85)

        # Bluff
        if _should_bluff_river(hole, board, interaction, is_aggressor, texture, pot, spr):
            if "bet" in available:
                bet_amount = int(pot * 0.66)
                br = allowed.get("betRange") or {}
                lo = int(br.get("min") or 1)
                hi = int(br.get("max") or lo)
                bet_amount = max(lo, min(bet_amount, hi))
                return RiverDecision("bet", bet_amount,
                    f"river bluff on {texture} board", 0.45)
            if "raise" in available:
                rr = allowed.get("raiseRange") or {}
                r_min = int(rr.get("min") or 1)
                r_max = int(rr.get("max") or r_min)
                return RiverDecision("raise", max(r_min, int(pot * 0.66)),
                    f"river bluff raise on {texture}", 0.40)

        # Thin value with marginal hands
        if interaction["has_pair"] and interaction["pair_type"] in ("middle",):
            if "bet" in available and spr > 3.0:
                thin_bet = int(pot * 0.33)
                br = allowed.get("betRange") or {}
                lo = int(br.get("min") or 1)
                hi = int(br.get("max") or lo)
                thin_bet = max(lo, min(thin_bet, hi))
                return RiverDecision("bet", thin_bet,
                    f"thin value {interaction['pair_type']} pair", 0.5)

        # Check behind
        if "check" in available:
            return RiverDecision("check", None,
                f"check behind with {strength:.0%} strength", 0.8)
        return RiverDecision("fold", None, "no action", 0.5)

    # ─── Facing a bet ──────────────────────────────────────────────

    # Made hand → raise
    if interaction["has_set"] or interaction["has_2pair"]:
        if "raise" in available:
            rr = allowed.get("raiseRange") or {}
            r_min = int(rr.get("min") or call_chips * 2)
            r_max = int(rr.get("max") or r_min)
            raise_amt = _river_sizing(strength, pot, spr, texture)
            raise_amt = max(r_min, min(raise_amt, r_max))
            return RiverDecision("raise", raise_amt,
                f"raise {hand_cls} for value on river", 0.95)
        if "call" in available:
            return RiverDecision("call", None,
                f"call {hand_cls} (no raise available)", 0.90)

    # Strong top pair → call or raise
    if interaction["pair_type"] == "top":
        if equity > 0.70 and "raise" in available:
            rr = allowed.get("raiseRange") or {}
            r_min = int(rr.get("min") or call_chips * 2)
            r_max = int(rr.get("max") or r_min)
            return RiverDecision("raise", max(r_min, int(call_chips * 2.3)),
                f"raise top pair for thin value on river", 0.65)
        if "call" in available:
            return RiverDecision("call", None,
                f"call top pair on river, {equity:.0%} eq", 0.65)

    # Bluff catcher
    if _is_bluff_catcher(interaction, equity, pot_odds):
        if "call" in available:
            # Adjust based on opponent
            if villain_archetype in ("LAG", "Maniac"):
                return RiverDecision("call", None,
                    f"bluff catch vs {villain_archetype}", 0.55)
            if call_chips <= pot * 0.5:
                return RiverDecision("call", None,
                    f"bluff catch, good price ({pot_odds:.0%})", 0.45)
            if "fold" in available:
                return RiverDecision("fold", None,
                    f"fold bluff catcher, bad price", 0.55)

    # Medium strength → call if odds justify
    if strength > 0.50:
        if equity >= pot_odds - 0.02 and "call" in available:
            if call_chips <= pot * 0.6:
                return RiverDecision("call", None,
                    f"call with {strength:.0%} strength, good odds", 0.50)

    # General call with equity
    if equity_result.has_direct_odds and "call" in available:
        return RiverDecision("call", None,
            f"call, {equity:.0%} eq vs {pot_odds:.0%}", 0.55)

    # Fold
    if "check" in available:
        return RiverDecision("check", None, "check option", 0.6)
    return RiverDecision("fold", None,
        f"fold river, {equity:.0%} eq vs {pot_odds:.0%} pot odds", 0.80)
