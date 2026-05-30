"""Range engine — position-based opening ranges, 3-bet ranges, defend ranges.

Provides complete preflop hand classification and range membership checks.
All ranges are data-driven and can be hot-reloaded from config.
"""

from __future__ import annotations

from typing import Optional

RANKS = "23456789TJQKA"

# ─── Position mapping ─────────────────────────────────────────────
# 6-max canonical seating: 1=BTN, 2=SB, 3=BB, 4=UTG, 5=MP, 6=CO
SEAT_TO_POS = {1: "BTN", 2: "SB", 3: "BB", 4: "UTG", 5: "MP", 6: "CO"}
POS_TO_SEAT = {v: k for k, v in SEAT_TO_POS.items()}


def seat_to_position(seat_num: int, n_players: int = 6) -> str:
    """Convert seat number to position label, adjusting for table size."""
    if n_players <= 2:
        return "BTN" if seat_num == 1 else "BB"
    if n_players <= 3:
        mapping = {1: "BTN", 2: "SB", 3: "BB"}
        return mapping.get(seat_num, "MP")
    return SEAT_TO_POS.get(seat_num, "MP")


def hand_class(hole: list[str]) -> str:
    """Convert hole cards to standard hand classification string.

    ['As','Ks'] -> 'AKs', ['Ah','Kd'] -> 'AKo', ['As','Ad'] -> 'AA'
    """
    if len(hole) != 2:
        return ""
    try:
        r1 = hole[0][0].upper()
        r2 = hole[1][0].upper()
        s1 = hole[0][-1].lower()
        s2 = hole[1][-1].lower()
    except IndexError:
        return ""
    if r1 not in RANKS or r2 not in RANKS:
        return ""
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2 = r2, r1
        s1, s2 = s2, s1
    if r1 == r2:
        return r1 + r2
    return f"{r1}{r2}{'s' if s1 == s2 else 'o'}"


# ─── Opening Ranges (RFI) by position ──────────────────────────────

OPENING_RANGES: dict[str, set] = {
    "UTG": {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88",
        "AKs", "AKo", "AQs", "AQo", "AJs", "ATs",
        "KQs", "KJs", "QJs",
    },
    "MP": {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs",
        "KQs", "KQo", "KJs", "KTs",
        "QJs", "QTs", "JTs", "T9s", "98s",
    },
    "CO": {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55",
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
        "KQs", "KQo", "KJs", "KJo", "KTs", "K9s",
        "QJs", "QJo", "QTs", "Q9s",
        "JTs", "J9s", "T9s", "98s", "87s",
        "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
    },
    "BTN": {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
        "A9s", "A9o", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
        "KQs", "KQo", "KJs", "KJo", "KTs", "KTo", "K9s", "K8s",
        "QJs", "QJo", "QTs", "Q9s", "Q8s",
        "JTs", "JTo", "J9s", "J8s",
        "T9s", "T8s", "98s", "97s", "87s", "86s", "76s", "75s",
        "65s", "54s",
    },
    "SB": {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
        "KQs", "KQo", "KJs", "KTs",
        "QJs", "QTs", "JTs", "T9s",
        "A9s", "A8s", "A7s", "A6s", "A5s",
    },
    "BB": {
        "AA", "KK", "QQ", "JJ", "TT", "99", "88",
        "AKs", "AKo", "AQs", "AQo", "AJs", "ATs",
        "KQs", "KJs", "QJs",
    },
}

# ─── 3-Bet Ranges ──────────────────────────────────────────────────

THREE_BET_RANGES: dict[str, set] = {
    "UTG": {"AA", "KK", "QQ", "JJ", "AKs", "AKo"},
    "MP": {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"},
    "CO": {"AA", "KK", "QQ", "JJ", "TT", "99", "AKs", "AKo", "AQs", "AQo", "AJs"},
    "BTN": {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "AKs", "AKo", "AQs", "AQo",
            "AJs", "ATs", "KQs", "KJs", "A5s", "A4s"},
    "SB": {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs", "AJs", "KQs"},
    "BB": {"AA", "KK", "QQ", "JJ", "AKs", "AKo", "AQs"},
}

# ─── 4-Bet+ Ranges ─────────────────────────────────────────────────

FOUR_BET_RANGES: dict[str, set] = {
    "UTG": {"AA", "KK", "QQ", "AKs"},
    "MP": {"AA", "KK", "QQ", "AKs", "AKo"},
    "CO": {"AA", "KK", "QQ", "JJ", "AKs", "AKo"},
    "BTN": {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"},
    "SB": {"AA", "KK", "QQ", "AKs", "AKo"},
    "BB": {"AA", "KK", "QQ", "AKs"},
}

FIVE_BET_ALL_IN: set = {"AA", "KK", "QQ", "AKs"}

# ─── Defend Ranges (facing RFI) ────────────────────────────────────

DEFEND_VS_OPEN: dict[str, set] = {
    # Range of hands to defend from BB vs various positions
    "vs_UTG": {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77",
               "AKs", "AKo", "AQs", "AQo", "AJs", "ATs",
               "KQs", "KJs", "QJs", "JTs", "T9s", "98s", "87s"},
    "vs_MP": {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66",
              "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs",
              "KQs", "KQo", "KJs", "KTs",
              "QJs", "QTs", "JTs", "T9s", "98s", "87s", "76s"},
    "vs_CO": {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55",
              "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
              "KQs", "KQo", "KJs", "KJo", "KTs", "K9s",
              "QJs", "QTs", "Q9s",
              "JTs", "J9s", "T9s", "98s", "87s", "76s", "65s",
              "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s"},
    "vs_BTN": {"AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33",
               "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
               "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
               "KQs", "KQo", "KJs", "KJo", "KTs", "KTo", "K9s", "K8s",
               "QJs", "QJo", "QTs", "Q9s",
               "JTs", "JTo", "J9s", "T9s", "T8s",
               "98s", "97s", "87s", "86s", "76s", "65s", "54s"},
}

# ─── Blind vs Blind ────────────────────────────────────────────────

SB_VS_BB_OPEN: set = {
    "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55",
    "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
    "KQs", "KQo", "KJs", "KJo", "KTs", "K9s",
    "QJs", "QJo", "QTs", "Q9s",
    "JTs", "J9s", "T9s", "98s", "87s", "76s",
    "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
}

BB_VS_SB_3BET: set = {
    "AA", "KK", "QQ", "JJ", "TT", "99",
    "AKs", "AKo", "AQs", "AQo", "AJs", "ATs",
    "KQs", "KJs", "QJs", "JTs",
}


def is_in_opening_range(hole: list[str], position: str) -> bool:
    """Check if hand is in the opening range for this position."""
    cls = hand_class(hole)
    return cls in OPENING_RANGES.get(position, set())


def is_in_3bet_range(hole: list[str], position: str) -> bool:
    """Check if hand is in the 3-bet range for this position."""
    cls = hand_class(hole)
    return cls in THREE_BET_RANGES.get(position, set())


def is_in_4bet_range(hole: list[str], position: str) -> bool:
    """Check if hand is in the 4-bet range for this position."""
    cls = hand_class(hole)
    return cls in FOUR_BET_RANGES.get(position, set())


def is_5bet_all_in(hole: list[str]) -> bool:
    """Check if hand is in the 5-bet all-in range."""
    cls = hand_class(hole)
    return cls in FIVE_BET_ALL_IN


def is_in_defend_range(hole: list[str], opener_position: str) -> bool:
    """Check if hand is in BB defend range vs opener's position."""
    cls = hand_class(hole)
    key = f"vs_{opener_position}"
    return cls in DEFEND_VS_OPEN.get(key, DEFEND_VS_OPEN.get("vs_MP", set()))


def is_in_sb_open(hole: list[str]) -> bool:
    """Check if hand is in SB steal range vs BB."""
    cls = hand_class(hole)
    return cls in SB_VS_BB_OPEN


def is_premium(hole: list[str]) -> bool:
    """Premium hands: QQ+, AK"""
    cls = hand_class(hole)
    return cls in {"AA", "KK", "QQ", "AKs", "AKo"}


def is_strong(hole: list[str]) -> bool:
    """Strong hands: JJ+, AQ+"""
    cls = hand_class(hole)
    return cls in {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs", "AQo", "AJs"}


def is_playable(hole: list[str], position: str = "BTN") -> bool:
    """Check if hand is playable from position (broader than opening range)."""
    cls = hand_class(hole)
    if is_premium(hole):
        return True
    if cls in OPENING_RANGES.get(position, set()):
        return True
    # Additional playable hands from LP
    if position in ("BTN", "CO"):
        return len(cls) >= 2  # Almost any sorted hand
    return False


def range_size(position: str) -> int:
    """Return the number of combos in a position's opening range."""
    return len(OPENING_RANGES.get(position, set()))


def range_vs_range_equity(hero_range: set, villain_range: set) -> float:
    """Approximate equity of hero_range vs villain_range.

    Uses a simplified model based on range composition.
    In production, replace with full enumeration or solver lookup."""
    hero_premium = len(hero_range & {"AA", "KK", "QQ", "AKs", "AKo"})
    villain_premium = len(villain_range & {"AA", "KK", "QQ", "AKs", "AKo"})
    h_total = max(len(hero_range), 1)
    v_total = max(len(villain_range), 1)

    hero_quality = 0.5 + 0.1 * (hero_premium / h_total) * 10
    villain_quality = 0.5 + 0.1 * (villain_premium / v_total) * 10

    return hero_quality / max(hero_quality + villain_quality, 0.01)
