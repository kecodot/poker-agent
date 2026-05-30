"""Flop strategy — board-texture-aware continuation betting and response.

Covers:
  - C-betting (dry vs wet boards, sizing by texture)
  - Facing cbets (call vs fold vs raise based on hand strength + texture)
  - Check-raising
  - Delayed c-bets
  - Multi-way adjustments
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from ..engine.hand_evaluator import evaluate_hand, hand_strength_from_rank, hand_class_name, _hand_class
from ..engine.equity_calculator import compute_full_equity, compute_pot_odds
from ..engine.range_engine import hand_class, seat_to_position
from ..engine.opponent_model import adjust_cbet_freq, adjust_bluff_freq, value_bet_thinner


@dataclass
class FlopDecision:
    action: str
    amount: Optional[int]
    reasoning: str
    confidence: float


def _board_texture(board: list[str]) -> str:
    """Classify flop texture.

    Returns: 'dry' | 'wet' | 'neutral'
    """
    if len(board) < 3:
        return "neutral"

    suits = [c[-1].lower() for c in board if len(c) >= 2]
    ranks_str = [c[0].upper() for c in board if c[0].upper() in "23456789TJQKA"]
    if len(ranks_str) < 3:
        return "neutral"

    ranks = sorted("23456789TJQKA".index(r) for r in ranks_str)
    monotone = len(set(suits)) == 1
    two_tone_flush = len(set(suits)) == 2 and max(suits.count(s) for s in set(suits)) >= 2
    connected = (max(ranks) - min(ranks)) <= 4
    paired = len(set(ranks_str)) < len(ranks_str)

    # Very wet: monotone or flush draw + connected
    if monotone:
        return "wet"
    if two_tone_flush and connected:
        return "wet"
    # Dry: paired and not connected
    if paired and not connected:
        return "dry"
    if connected:
        return "wet"
    if two_tone_flush:
        return "neutral"

    # Rainbow unconnected -> dry
    return "dry"


def _flop_sizing(texture: str, street: str = "flop") -> float:
    """Optimal bet sizing fraction of pot based on board texture."""
    sizing = {
        "dry":      {"flop": 0.33, "turn": 0.50, "river": 0.66},
        "wet":      {"flop": 0.66, "turn": 0.75, "river": 0.75},
        "neutral":  {"flop": 0.50, "turn": 0.60, "river": 0.66},
    }
    return sizing.get(texture, sizing["neutral"]).get(street, 0.5)


def _hand_strength_by_board_interaction(hole: list[str], board: list[str]) -> dict:
    """Detailed analysis of how hole cards interact with the flop.

    Returns:
        {
            'has_pair': bool,       # Top/bottom/middle pair or better
            'pair_type': str,       # 'top' | 'middle' | 'bottom' | 'over' | 'none'
            'has_draw': bool,       # Flush or straight draw
            'draw_type': str,       # 'flush' | 'open_ended' | 'gutshot' | 'combo' | 'none'
            'has_2pair': bool,
            'has_set': bool,
            'board_rank': int,      # Absolute hand rank
            'strength': float,      # 0.0-1.0
            'hand_class': str,      # Description
        }
    """
    if len(board) < 3:
        return {"has_pair": False, "pair_type": "none", "has_draw": False,
                "draw_type": "none", "has_2pair": False, "has_set": False,
                "board_rank": 7462, "strength": 0.5, "hand_class": "preflop"}

    ranks = "23456789TJQKA"
    hole_ranks = [c[0].upper() for c in hole]
    hole_suits = [c[-1].lower() for c in hole]
    board_ranks = [c[0].upper() for c in board]
    board_suits = [c[-1].lower() for c in board]

    # Pair detection
    all_ranks = hole_ranks + board_ranks
    rank_counts = {}
    for r in all_ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1

    # Check for pairs involving hole cards
    hole_paired = any(rank_counts.get(r, 0) >= 2 for r in hole_ranks)
    has_set = any(rank_counts.get(r, 0) >= 3 for r in hole_ranks)
    has_2pair = sum(1 for r in set(hole_ranks) if rank_counts.get(r, 0) >= 2) >= 2
    if not has_2pair:
        # Hole cards pair with one board card each
        has_2pair = (rank_counts.get(hole_ranks[0], 0) >= 2 and
                     rank_counts.get(hole_ranks[1], 0) >= 2)

    # Pair type
    pair_type = "none"
    if has_set:
        pair_type = "set"
    elif hole_paired and not has_2pair:
        # Determine if top/middle/bottom pair
        board_sorted = sorted(set(board_ranks), key=lambda x: ranks.index(x), reverse=True)
        paired_rank = next((r for r in hole_ranks if rank_counts.get(r, 0) >= 2), "")
        if paired_rank and board_sorted:
            if ranks.index(paired_rank) >= ranks.index(board_sorted[0]):
                pair_type = "top"
            elif len(board_sorted) > 1 and ranks.index(paired_rank) >= ranks.index(board_sorted[1]):
                pair_type = "middle"
            else:
                pair_type = "bottom"
    elif has_2pair:
        pair_type = "two_pair"

    # Draw detection
    has_draw = False
    draw_type = "none"

    # Flush draw: two hole cards same suit + 2+ board cards same suit
    for s in set(hole_suits):
        board_same_suit = sum(1 for bs in board_suits if bs == s)
        hole_same_suit = sum(1 for hs in hole_suits if hs == s)
        if hole_same_suit == 2 and board_same_suit >= 2:
            has_draw = True
            draw_type = "flush"
            break

    # Straight draw (check connectedness)
    if not has_draw:
        all_rank_idxs = sorted(set(ranks.index(r) for r in all_ranks if r in ranks))
        hole_idxs = sorted(ranks.index(r) for r in hole_ranks if r in ranks)

        # Open-ended: 4 consecutive ranks with one of ours at the end
        for i in range(len(all_rank_idxs) - 3):
            window = all_rank_idxs[i:i+4]
            if window[3] - window[0] == 3 and (window[0] in hole_idxs or window[3] in hole_idxs):
                has_draw = True
                draw_type = "open_ended" if draw_type == "none" else "combo"
                break

        # Gutshot: 4 out of 5 consecutive ranks
        if not has_draw:
            for i in range(len(all_rank_idxs) - 4):
                window = all_rank_idxs[i:i+5]
                if window[4] - window[0] <= 5 and any(h in hole_idxs for h in window):
                    has_draw = True
                    draw_type = "gutshot"
                    break

    # Hand rank
    board_rank = evaluate_hand(hole, board)
    strength = hand_strength_from_rank(board_rank)

    # Hand class description
    hc = hand_class_name(board_rank)

    return {
        "has_pair": hole_paired,
        "pair_type": pair_type,
        "has_draw": has_draw,
        "draw_type": "combo" if (has_draw and draw_type == "flush" and
                                 any("open_ended" in d for d in [draw_type]))
                     else draw_type,
        "has_2pair": has_2pair,
        "has_set": has_set,
        "board_rank": board_rank,
        "strength": strength,
        "hand_class": hc,
    }


def decide_flop(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> FlopDecision:
    """Main flop decision function."""
    if opponent_archetypes is None:
        opponent_archetypes = {}

    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = int(table.get("potChips") or 0)
    board = list(table.get("boardCards") or [])
    big_blind = int(table.get("bigBlindChips") or 2)
    active_opponents = len([s for s in table.get("seats", [])
                           if s.get("stackChips", 0) > 0 and
                           s.get("seatNumber") != table.get("selfSeatNumber")])

    texture = _board_texture(board)
    interaction = _hand_strength_by_board_interaction(hole, board)

    # Equity
    equity_result = compute_full_equity(
        hole, board, pot, call_chips,
        effective_stack=int(stack_depth_bb * big_blind),
        n_opponents=active_opponents,
        street="Flop",
        deadline_ms=150,
    )

    # Opponent adjustments
    villain_archetype = list(opponent_archetypes.values())[0] if opponent_archetypes else "Unknown"
    base_cbet_freq = 0.65
    cbet_freq = adjust_cbet_freq(base_cbet_freq,
                                 opponent_archetypes.get("fold_to_cbet", "unknown") if hasattr(opponent_archetypes, 'get') else "unknown")
    bluff_freq = adjust_bluff_freq(0.25, villain_archetype)

    size_frac = _flop_sizing(texture, "flop")
    bet_size = int(pot * size_frac)
    in_position = self_position in ("BTN", "CO")

    # --- Unopened (can check or bet) ---------------------------------
    if call_chips == 0:
        # Value-oriented: only bet when we have significant equity or made hand
        has_strong = (interaction["has_set"] or interaction["has_2pair"] or
                      interaction["pair_type"] == "top" or
                      interaction["strength"] > 0.70)

        if has_strong and "bet" in available:
            vbet_frac = 0.50 if texture == "dry" else _flop_sizing(texture, "flop")
            return FlopDecision("bet", int(pot * vbet_frac),
                f"value bet {interaction['hand_class']} on {texture} flop", 0.85)

        # Aggressor with pair/draw on dry boards: small c-bet
        if is_aggressor and in_position and "bet" in available:
            if interaction["has_draw"] and random.random() < 0.40:
                return FlopDecision("bet", int(pot * 0.40),
                    f"semi-bluff {interaction['draw_type']} draw", 0.55)
            if (interaction["has_pair"] and
                  interaction["pair_type"] in ("middle", "bottom") and
                  texture == "dry"):
                return FlopDecision("bet", int(pot * 0.35),
                    f"cbet {interaction['pair_type']} pair on dry flop", 0.60)

        # Default: check and realize equity with position
        if "check" in available:
            return FlopDecision("check", None,
                f"check {texture} flop", 0.75)

        return FlopDecision("fold", None, "no free option", 0.5)

    # --- Facing a bet -------------------------------------------------
    pot_odds = compute_pot_odds(call_chips, pot)

    # Strong hands -> raise
    if interaction["has_set"] or interaction["has_2pair"]:
        if "raise" in available:
            rr = allowed.get("raiseRange") or {}
            r_min = int(rr.get("min") or call_chips * 2)
            r_max = int(rr.get("max") or r_min)
            raise_amt = max(r_min, min(int(call_chips * 3 + pot * 0.3), r_max))
            return FlopDecision("raise", raise_amt,
                f"raise {interaction['hand_class']} on {texture}", 0.92)
        if "call" in available:
            return FlopDecision("call", None,
                f"call {interaction['hand_class']} (raise not available)", 0.85)

    # Top pair -> call or raise
    if interaction["pair_type"] == "top":
        if equity_result.equity > 0.70 and "raise" in available:
            rr = allowed.get("raiseRange") or {}
            r_min = int(rr.get("min") or call_chips * 2)
            r_max = int(rr.get("max") or r_min)
            raise_amt = max(r_min, min(int(call_chips * 2.5), r_max))
            return FlopDecision("raise", raise_amt,
                f"raise top pair on {texture}", 0.78)
        if equity_result.equity >= pot_odds - 0.03 and "call" in available:
            return FlopDecision("call", None,
                f"call top pair, {equity_result.equity:.0%} vs {pot_odds:.0%}", 0.7)

    # Draw -> call with implied odds
    if interaction["has_draw"] and equity_result.has_implied_odds:
        if "call" in available:
            return FlopDecision("call", None,
                f"draw {interaction['draw_type']}, implied odds", 0.55)

    # Float bluff in position vs nitty/TAG players
    if (in_position and villain_archetype in ("Nit", "TAG") and
            "call" in available and call_chips <= pot * 0.5):
        if not interaction["has_pair"] and not interaction["has_draw"]:
            return FlopDecision("call", None,
                f"float {texture} flop vs {villain_archetype}", 0.4)

    # General: call if equity > pot_odds
    if equity_result.has_direct_odds and "call" in available:
        return FlopDecision("call", None,
            f"call, {equity_result.equity:.0%} eq vs {pot_odds:.0%} po", 0.55)

    # Any pair or draw at reasonable price
    if (interaction["has_pair"] or interaction["has_draw"]) and "call" in available:
        if call_chips <= pot * 0.8:
            return FlopDecision("call", None,
                f"call {interaction.get('pair_type', interaction.get('draw_type', 'marginal'))} hand", 0.42)

    # Fold
    if "check" in available:
        return FlopDecision("check", None, "free option", 0.6)
    return FlopDecision("fold", None,
        f"fold on {texture} flop, {equity_result.equity:.0%} eq vs {pot_odds:.0%} po", 0.75)
