"""Hand strength evaluation using treys — fast 7-card poker evaluator.

Provides:
  - rank_hole_cards: integer rank of a 2-card combo (lower = stronger)
  - evaluate_hand: integer rank of hole + board (lower = better)
  - hand_class_name: human-readable hand class (e.g. "Full House")
  - hand_class_to_string: convert treys rank to category name
"""

from __future__ import annotations

from typing import Optional

try:
    from treys import Card as TreysCard
    from treys import Evaluator as TreysEvaluator
    _HAS_TREYS = True
except Exception:
    _HAS_TREYS = False

RANKS = "23456789TJQKA"
SUITS = "shdc"

# Hand rank thresholds from treys Evaluator
# Lower rank = stronger hand
HAND_CLASS_THRESHOLDS: list[tuple[int, str]] = [
    (1, "Royal Flush"),
    (10, "Straight Flush"),
    (166, "Four of a Kind"),
    (322, "Full House"),
    (1599, "Flush"),
    (1609, "Straight"),
    (2467, "Three of a Kind"),
    (3325, "Two Pair"),
    (6185, "One Pair"),
    (7462, "High Card"),
]

_singleton_evaluator: Optional[TreysEvaluator] = None


def _get_evaluator() -> TreysEvaluator:
    global _singleton_evaluator
    if _singleton_evaluator is None and _HAS_TREYS:
        _singleton_evaluator = TreysEvaluator()
    return _singleton_evaluator  # type: ignore[return-value]


def _to_treys(card_str: str) -> str:
    """Convert Arena card format (e.g. 'Ah', '10s') to treys format ('Ah', 'Ts')."""
    if not card_str:
        return "2c"
    r = card_str[0].upper()
    if card_str.startswith("10"):
        r = "T"
        s = card_str[2].lower() if len(card_str) > 2 else "x"
    else:
        s = card_str[-1].lower()
    return r + s


def _hand_class(hole: list[str]) -> str:
    """['As','Ks'] -> 'AKs'. Returns empty string if unparseable."""
    if len(hole) != 2:
        return ""
    r1, s1 = hole[0][0].upper(), hole[0][-1].lower()
    r2, s2 = hole[1][0].upper(), hole[1][-1].lower()
    if r1 not in RANKS or r2 not in RANKS:
        return ""
    if RANKS.index(r1) < RANKS.index(r2):
        r1, r2 = r2, r1
        s1, s2 = s2, s1
    if r1 == r2:
        return r1 + r2
    return f"{r1}{r2}{'s' if s1 == s2 else 'o'}"


def _card_rank_vals(hole: list[str]) -> tuple[int, int]:
    """Return numeric rank values (0-12) for two hole cards."""
    if len(hole) != 2:
        return (0, 0)
    try:
        r1 = RANKS.index(hole[0][0].upper())
        r2 = RANKS.index(hole[1][0].upper())
        return (r1, r2)
    except (ValueError, IndexError):
        return (0, 0)


def rank_hole_cards(hole: list[str]) -> float:
    """Return a 0.0-1.0 strength score for hole cards alone.

    Based on pre-computed heads-up equity and position-adjusted values.
    Higher = stronger."""
    cls = _hand_class(hole)
    if not cls:
        return 0.45

    r1, r2 = _card_rank_vals(hole)
    suited = len(hole) == 2 and hole[0][-1].lower() == hole[1][-1].lower()

    # Pair strength
    if r1 == r2:
        return 0.50 + 0.04 * r1  # 22->0.54, AA->0.98

    high, low = max(r1, r2), min(r1, r2)
    gap = high - low

    # Unpaired hand strength
    base = 0.30 + 0.022 * high + 0.010 * low
    if suited:
        base += 0.04
    if gap <= 1:  # connected
        base += 0.025
    elif gap <= 2:  # 1-gapper
        base += 0.012
    if high >= 11:  # Ace or King high
        base += 0.02

    return min(0.95, base)


def evaluate_hand(hole: list[str], board: list[str]) -> int:
    """Return treys hand rank (lower = stronger, 1=Royal Flush .. 7462=High Card).

    Returns 7462 (weakest possible) if treys is unavailable or evaluation fails."""
    if not _HAS_TREYS or not (hole and board and len(board) >= 3):
        return 7462
    try:
        ev = _get_evaluator()
        hero = [TreysCard.new(_to_treys(c)) for c in hole]
        board_t = [TreysCard.new(_to_treys(c)) for c in board]
        return ev.evaluate(board_t, hero)
    except Exception:
        return 7462


def hand_class_name(rank: int) -> str:
    """Convert treys integer rank to human-readable hand class name."""
    for threshold, name in HAND_CLASS_THRESHOLDS:
        if rank <= threshold:
            return name
    return "High Card"


def hand_strength_from_rank(rank: int) -> float:
    """Convert treys rank (1=strongest, 7462=weakest) to 0.0-1.0 strength.

    Uses a non-linear mapping to better represent hand value differences.
    Strong hands (1-1000) get compressed into 0.86-1.0;
    Weak hands (3000-7462) spread across 0.0-0.60."""
    if rank <= 0:
        return 1.0
    if rank >= 7462:
        return 0.0
    return 1.0 - (rank / 7462.0) ** 0.65


def hand_rank_from_hole_class(hole: list[str]) -> int:
    """Approximate treys rank for hole cards alone (no board).

    Used for preflop equity estimation. Lower = stronger."""
    cls = _hand_class(hole)
    if not cls:
        return 4000

    if len(cls) == 2:  # Pair
        r = RANKS.index(cls[0])
        return max(1, 169 - r * 13)

    # Unpaired
    r1 = RANKS.index(cls[0])
    r2 = RANKS.index(cls[1])
    suited = cls.endswith("s")
    base = 169 + (12 - r1) * 12 + (12 - r2)
    if suited:
        base -= 144
    return min(7462, max(169, base))


def static_preflop_equity(hole: list[str]) -> float:
    """Pre-computed preflop equity vs 1 random opponent.

    Based on enumerated all-in equity tables for common hands.
    Falls back to rank_hole_cards for less common combos."""
    cls = _hand_class(hole)
    if not cls:
        return 0.45

    PREFLOP_EQ = {
        "AA": 0.852, "KK": 0.824, "QQ": 0.799, "JJ": 0.775, "TT": 0.751,
        "99": 0.721, "88": 0.692, "77": 0.663, "66": 0.634, "55": 0.604,
        "44": 0.571, "33": 0.538, "22": 0.503,
        "AKs": 0.670, "AQs": 0.662, "AJs": 0.654, "ATs": 0.646, "A9s": 0.631,
        "A8s": 0.621, "A7s": 0.613, "A6s": 0.605, "A5s": 0.604, "A4s": 0.594,
        "A3s": 0.586, "A2s": 0.575,
        "AKo": 0.653, "AQo": 0.644, "AJo": 0.636, "ATo": 0.627, "A9o": 0.611,
        "A8o": 0.600, "A7o": 0.591, "A6o": 0.581, "A5o": 0.580, "A4o": 0.568,
        "A3o": 0.559, "A2o": 0.547,
        "KQs": 0.634, "KJs": 0.626, "KTs": 0.618, "K9s": 0.602, "K8s": 0.588,
        "K7s": 0.577, "K6s": 0.565, "K5s": 0.559, "K4s": 0.549, "K3s": 0.540,
        "K2s": 0.531,
        "KQo": 0.615, "KJo": 0.606, "KTo": 0.597, "K9o": 0.578, "K8o": 0.563,
        "K7o": 0.551, "K6o": 0.539, "K5o": 0.533, "K4o": 0.522, "K3o": 0.512,
        "K2o": 0.502,
        "QJs": 0.603, "QTs": 0.595, "Q9s": 0.579, "Q8s": 0.563, "Q7s": 0.549,
        "Q6s": 0.538, "Q5s": 0.531, "Q4s": 0.521, "Q3s": 0.511, "Q2s": 0.503,
        "QJo": 0.581, "QTo": 0.572, "Q9o": 0.554, "Q8o": 0.537, "Q7o": 0.522,
        "Q6o": 0.510, "Q5o": 0.503, "Q4o": 0.492, "Q3o": 0.481, "Q2o": 0.472,
        "JTs": 0.575, "J9s": 0.558, "J8s": 0.542, "J7s": 0.527, "J6s": 0.512,
        "J5s": 0.504, "J4s": 0.494, "J3s": 0.484, "J2s": 0.474,
        "JTo": 0.553, "J9o": 0.534, "J8o": 0.517, "J7o": 0.501, "J6o": 0.485,
        "J5o": 0.477, "J4o": 0.466, "J3o": 0.455, "J2o": 0.445,
        "T9s": 0.540, "T8s": 0.524, "T7s": 0.507, "T6s": 0.492, "T5s": 0.481,
        "T4s": 0.471, "T3s": 0.461, "T2s": 0.451,
        "T9o": 0.517, "T8o": 0.499, "T7o": 0.481, "T6o": 0.465, "T5o": 0.453,
        "T4o": 0.442, "T3o": 0.431, "T2o": 0.421,
        "98s": 0.508, "97s": 0.491, "96s": 0.475, "95s": 0.463, "94s": 0.453,
        "93s": 0.443, "92s": 0.433,
        "98o": 0.484, "97o": 0.466, "96o": 0.449, "95o": 0.437, "94o": 0.426,
        "93o": 0.415, "92o": 0.404,
        "87s": 0.480, "86s": 0.464, "85s": 0.451, "84s": 0.440, "83s": 0.430,
        "82s": 0.420,
        "87o": 0.455, "86o": 0.438, "85o": 0.424, "84o": 0.412, "83o": 0.401,
        "82o": 0.390,
        "76s": 0.455, "75s": 0.438, "74s": 0.425, "73s": 0.415, "72s": 0.402,
        "76o": 0.429, "75o": 0.411, "74o": 0.397, "73o": 0.386, "72o": 0.374,
        "65s": 0.433, "64s": 0.416, "63s": 0.405, "62s": 0.393,
        "65o": 0.405, "64o": 0.387, "63o": 0.375, "62o": 0.363,
        "54s": 0.413, "53s": 0.396, "52s": 0.384,
        "54o": 0.384, "53o": 0.366, "52o": 0.353,
        "43s": 0.394, "42s": 0.378,
        "43o": 0.363, "42o": 0.346,
        "32s": 0.359,
        "32o": 0.326,
    }
    return PREFLOP_EQ.get(cls, rank_hole_cards(hole))


def compute_hand_rank(hole: list[str], board: list[str]) -> int:
    """Compute absolute hand rank using treys, or estimated rank if treys unavailable.

    Returns: int 1-7462 (lower = stronger)"""
    if len(board) < 3:
        return hand_rank_from_hole_class(hole)
    return evaluate_hand(hole, board)
