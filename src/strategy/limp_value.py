"""Limp-Value Strategy — exploits passive calling stations.

Ported from the baseline strategy in arena_stress_test.py.
This is the proven winner against loose-passive bots:
- Limps wide (costs 1 BB instead of 2.2 BB)
- Calls down light postflop (exploits excessive bluffing)
- Only raises premiums preflop and strong hands postflop
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

RANKS = "23456789TJQKA"
RANK_ORDER = {r: i for i, r in enumerate(RANKS)}


@dataclass
class LimpValueDecision:
    action: str
    amount: Optional[int]
    reasoning: str
    confidence: float


def _preflop_strength(hole: list[str]) -> float:
    """Simple preflop hand strength: 0.0-0.95."""
    r1, r2 = hole[0][0].upper(), hole[1][0].upper()
    suited = hole[0][1].lower() == hole[1][1].lower()
    i1, i2 = RANK_ORDER.get(r1, 0), RANK_ORDER.get(r2, 0)
    if i1 < i2:
        i1, i2 = i2, i1
    pair_bonus = 0.18 if r1 == r2 else 0.0
    high_bonus = (i1 + i2) / 24.0 * 0.35
    suited_bonus = 0.04 if suited else 0.0
    connected_bonus = 0.03 if abs(i1 - i2) <= 2 and r1 != r2 else 0.0
    return min(0.95, 0.30 + pair_bonus + high_bonus + suited_bonus + connected_bonus)


def _postflop_strength(hole: list[str], board: list[str]) -> float:
    """Postflop hand strength: 0.0-1.0 using rank/suit counting."""
    if len(board) < 3:
        return _preflop_strength(hole)

    all_cards = hole + board
    ranks = [c[0].upper() for c in all_cards]
    suits = [c[1].lower() for c in all_cards]

    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    suit_counts = {}
    for s in suits:
        suit_counts[s] = suit_counts.get(s, 0) + 1

    # Check for flush
    flush_suit = None
    for s, n in suit_counts.items():
        if n >= 5:
            flush_suit = s
            break

    # Check for straight
    rank_vals = sorted(set(RANK_ORDER[r] for r in ranks))
    straight_high = -1
    for i in range(len(rank_vals) - 4):
        if rank_vals[i + 4] - rank_vals[i] == 4:
            straight_high = rank_vals[i + 4]
    if set([12, 0, 1, 2, 3]).issubset(set(rank_vals)):
        straight_high = 3  # A-2-3-4-5 straight

    counts = sorted(rank_counts.values(), reverse=True)

    # Scoring
    score = 0.0

    if flush_suit and straight_high >= 0:
        if straight_high == 12:
            score = 1.0   # Royal
        else:
            score = 0.92 + straight_high * 0.006
    elif counts[0] == 4:
        score = 0.88
    elif counts[0] == 3 and counts[1] >= 2:
        score = 0.84
    elif flush_suit is not None:
        score = 0.70 + sum(RANK_ORDER[r] for r in ranks if any(
            c[0].upper() == r and c[1].lower() == flush_suit for c in all_cards
        )) / 100.0 * 0.10
    elif straight_high >= 0:
        score = 0.60 + straight_high * 0.015
    elif counts[0] == 3:
        score = 0.50 + sum(RANK_ORDER[r] for r, c in rank_counts.items() if c == 3) * 0.008
    elif counts[0] == 2 and counts[1] == 2:
        score = 0.42
    elif counts[0] == 2:
        score = 0.32 + sum(RANK_ORDER[r] for r, c in rank_counts.items() if c == 2) * 0.006
    else:
        score = 0.20 + sum(RANK_ORDER[r] for r in ranks) / len(ranks) * 0.15 / 7.0

    return min(0.98, score)


def decide_preflop_limp_value(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
) -> LimpValueDecision:
    """Preflop decision using baseline limp-heavy approach.

    Strategy: limp most playable hands, raise only premiums.
    This exploits passive calling stations by keeping pots small
    and realizing equity cheaply.
    """
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    strength = _preflop_strength(hole)

    if call_chips == 0:
        # Unopened pot
        if "check" in available:
            # BB option — check premium hands and raise them
            if strength > 0.65 and "raise" in available:
                return LimpValueDecision("raise", pot * 3,
                    f"limp-value: raise premium {hole}", 0.85)
            return LimpValueDecision("check", None,
                f"limp-value: check {hole} (BB option)", 0.7)
        # BTN/SB: raise premiums, limp playable
        if strength > 0.65 and "raise" in available:
            return LimpValueDecision("raise", pot * 3,
                f"limp-value: raise premium {hole}", 0.85)
        if strength > 0.35 and "call" in available:
            return LimpValueDecision("call", None,
                f"limp-value: limp {hole}", 0.55)
        return LimpValueDecision("fold", None,
            f"limp-value: fold trash {hole}", 0.8)
    else:
        # Facing a bet/raise
        call_pct = call_chips / max(pot + call_chips, 1)
        if strength > 0.75 and "raise" in available:
            return LimpValueDecision("raise", call_chips * 3,
                f"limp-value: 3bet premium {hole}", 0.85)
        if call_pct < 0.5 and "call" in available:
            return LimpValueDecision("call", None,
                f"limp-value: call {hole}, {call_pct:.0%} pot", 0.5)
        if "check" in available:
            return LimpValueDecision("check", None,
                f"limp-value: option check", 0.7)
        return LimpValueDecision("fold", None,
            f"limp-value: fold {hole} to bet", 0.8)


def decide_flop_limp_value(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> LimpValueDecision:
    """Flop decision using baseline passive approach.

    Value bet strong hands, call down with any piece (strength > 0.30).
    This exploits aggressive bots that bluff too much.
    """
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    board = list(table.get("boardCards") or [])
    strength = _postflop_strength(hole, board)

    if call_chips == 0:
        if strength > 0.70 and "bet" in available:
            return LimpValueDecision("bet", pot // 2,
                f"limp-value: value bet {strength:.0%}", 0.75)
        if "check" in available:
            return LimpValueDecision("check", None,
                f"limp-value: check flop", 0.7)
        return LimpValueDecision("fold", None, "no free option", 0.5)
    else:
        if strength > 0.70 and "raise" in available:
            return LimpValueDecision("raise", call_chips * 3,
                f"limp-value: raise {strength:.0%}", 0.8)
        if strength > 0.30 and "call" in available:
            return LimpValueDecision("call", None,
                f"limp-value: call down {strength:.0%}", 0.45)
        if "check" in available:
            return LimpValueDecision("check", None, "limp-value: free", 0.6)
        return LimpValueDecision("fold", None,
            f"limp-value: fold {strength:.0%}", 0.75)


def decide_turn_limp_value(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> LimpValueDecision:
    """Turn decision — same passive approach as flop."""
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    board = list(table.get("boardCards") or [])
    strength = _postflop_strength(hole, board)

    if call_chips == 0:
        if strength > 0.70 and "bet" in available:
            return LimpValueDecision("bet", pot // 2,
                f"limp-value: turn value bet {strength:.0%}", 0.75)
        if "check" in available:
            return LimpValueDecision("check", None, "limp-value: check turn", 0.7)
        return LimpValueDecision("fold", None, "no free option", 0.5)
    else:
        if strength > 0.70 and "raise" in available:
            return LimpValueDecision("raise", call_chips * 3,
                f"limp-value: turn raise {strength:.0%}", 0.8)
        if strength > 0.30 and "call" in available:
            return LimpValueDecision("call", None,
                f"limp-value: turn call {strength:.0%}", 0.4)
        if "check" in available:
            return LimpValueDecision("check", None, "free turn", 0.6)
        return LimpValueDecision("fold", None,
            f"limp-value: turn fold {strength:.0%}", 0.75)


def decide_river_limp_value(
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str] = None,
    stack_depth_bb: float = 100.0,
    self_position: str = "",
    is_aggressor: bool = False,
) -> LimpValueDecision:
    """River decision — value-heavy, thin calls vs aggressive bots."""
    allowed = table.get("allowedActions") or {}
    available = allowed.get("availableActions") or []
    call_chips = int(allowed.get("callChips") or 0)
    pot = max(int(table.get("potChips") or 0), 1)
    board = list(table.get("boardCards") or [])
    strength = _postflop_strength(hole, board)

    if call_chips == 0:
        if strength > 0.65 and "bet" in available:
            return LimpValueDecision("bet", pot // 2,
                f"limp-value: river value bet {strength:.0%}", 0.8)
        if "check" in available:
            return LimpValueDecision("check", None, "limp-value: check river", 0.7)
        return LimpValueDecision("fold", None, "no free option", 0.5)
    else:
        # River: call a bit tighter than flop/turn
        if strength > 0.65 and "raise" in available:
            return LimpValueDecision("raise", call_chips * 2,
                f"limp-value: river raise {strength:.0%}", 0.85)
        if strength > 0.45 and "call" in available and call_chips <= pot * 0.6:
            return LimpValueDecision("call", None,
                f"limp-value: thin river call {strength:.0%}", 0.4)
        if strength > 0.30 and "call" in available and call_chips <= pot * 0.3:
            return LimpValueDecision("call", None,
                f"limp-value: bluff catch {strength:.0%}", 0.35)
        if "check" in available:
            return LimpValueDecision("check", None, "free river", 0.6)
        return LimpValueDecision("fold", None,
            f"limp-value: river fold {strength:.0%}", 0.8)
