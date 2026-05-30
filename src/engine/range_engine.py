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
        # All pairs
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
        # Broadway
        "AKs", "AKo", "AQs", "AQo", "AJs", "AJo", "ATs", "ATo",
        "KQs", "KQo", "KJs", "KJo", "KTs", "KTo",
        "QJs", "QJo", "QTs", "QTo",
        "JTs", "JTo",
        # All suited aces
        "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
        # Suited kings
        "K9s", "K8s", "K7s", "K6s", "K5s", "K4s", "K3s", "K2s",
        # Suited queens
        "Q9s", "Q8s", "Q7s", "Q6s", "Q5s",
        # Suited jacks
        "J9s", "J8s", "J7s",
        # Suited connectors and gappers
        "T9s", "T8s", "T7s",
        "98s", "97s", "96s",
        "87s", "86s", "85s",
        "76s", "75s", "74s",
        "65s", "64s",
        "54s", "53s",
        "43s",
        # Offsuit aces (steal/wider BTN)
        "A9o", "A8o", "A7o", "A6o", "A5o", "A4o", "A3o", "A2o",
        # Offsuit broadway-ish
        "K9o", "Q9o", "J9o", "T9o",
        # More suited
        "KTo", "QTo",
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

# ─── Heads-Up BTN Opening Range ─────────────────────────────────────
# Against calling stations, BTN must play tight (~50% VPIP).
# Raising 2.2 BB with trash loses more than folding 0.5 BB.
# Only open hands with robust equity: pairs, suited aces, suited
# broadway, suited connectors, and offsuit aces/broadway.

HU_BTN_FOLD = {
    # ── Offsuit non-ace hands with a card ≤ 8 ──
    # Deuce kickers (A2o stays)
    "32o", "42o", "52o", "62o", "72o", "82o", "92o", "T2o", "J2o", "Q2o", "K2o",
    # Trey kickers (A3o stays)
    "43o", "53o", "63o", "73o", "83o", "93o", "T3o", "J3o", "Q3o", "K3o",
    # Four kickers (A4o stays, 54o stays)
    "64o", "74o", "84o", "94o", "T4o", "J4o", "Q4o", "K4o",
    # Five kickers (A5o stays, 65o stays, 54o stays)
    "75o", "85o", "95o", "T5o", "J5o", "Q5o", "K5o",
    # Six kickers (A6o stays, 76o stays, 65o stays)
    "86o", "96o", "T6o", "J6o", "Q6o", "K6o",
    # Seven kickers (A7o stays, 87o stays, 76o stays)
    "97o", "T7o", "J7o", "Q7o", "K7o",
    # Eight kickers (A8o stays, 98o stays, 87o stays)
    "T8o", "J8o", "Q8o", "K8o",
    # Nine kickers (A9o stays, T9o stays, 98o stays)
    "J9o", "Q9o", "K9o",
    # ── Weak suited hands (gap > 2, no high-card value) ──
    "32s", "42s", "52s", "62s", "72s", "82s", "92s",
    "43s", "53s", "63s", "73s", "83s", "93s",
    "J2s", "J3s", "J4s", "J5s", "J6s",
    "Q2s", "Q3s", "Q4s", "Q5s", "Q6s",
    "K2s", "K3s", "K4s",
    "T2s", "T3s", "T4s", "T5s",
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


def is_in_opening_range(hole: list[str], position: str, n_players: int = 6) -> bool:
    """Check if hand is in the opening range for this position.

    In heads-up, BTN/SB opens much wider (~80% instead of ~40%).
    """
    cls = hand_class(hole)
    if position in OPENING_RANGES:
        if cls in OPENING_RANGES[position]:
            return True
    # HU BTN: play all but absolute trash
    if n_players <= 2 and position == "BTN":
        return cls not in HU_BTN_FOLD
    return False


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
    """Check if hand is playable from position (broader than opening range).

    Returns True for hands with reasonable equity potential.
    Filters out only the worst trash (e.g. 72o, 83o, 92o)."""
    cls = hand_class(hole)
    if not cls or len(cls) < 2:
        return False
    if is_premium(hole):
        return True
    if cls in OPENING_RANGES.get(position, set()):
        return True
    # Additional playable hands from LP: any suited, any pair, any Broadway+
    if position in ("BTN", "CO"):
        if cls.endswith("s"):
            return True     # Any suited hand
        if len(cls) == 2:
            return True     # Any pair
        # Offsuit: need at least one Broadway card (T+) and some connectivity
        r1, r2 = cls[0], cls[1]
        if r1 in "AKQJT" or r2 in "AKQJT":
            return True     # Any hand with a Broadway card
        # Connected low offsuit: 98o-54o
        ri1, ri2 = RANKS.index(r1), RANKS.index(r2)
        if abs(ri1 - ri2) <= 2:
            return True
        return False
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
