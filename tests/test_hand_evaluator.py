"""Tests for hand_evaluator module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.hand_evaluator import (
    _hand_class,
    rank_hole_cards,
    static_preflop_equity,
    hand_strength_from_rank,
    hand_class_name,
    hand_rank_from_hole_class,
)


def test_hand_class_pairs():
    assert _hand_class(["As", "Ad"]) == "AA"
    assert _hand_class(["Kh", "Ks"]) == "KK"
    assert _hand_class(["2c", "2d"]) == "22"
    assert _hand_class(["Th", "Ts"]) == "TT"


def test_hand_class_suited():
    assert _hand_class(["As", "Ks"]) == "AKs"
    assert _hand_class(["Kh", "Qh"]) == "KQs"


def test_hand_class_offsuit():
    assert _hand_class(["Ah", "Kd"]) == "AKo"
    assert _hand_class(["Qc", "Js"]) == "QJo"


def test_hand_class_ordering():
    # Lower ranked card first in input, should normalize
    assert _hand_class(["Kd", "Ah"]) == "AKo"
    assert _hand_class(["Qs", "Ac"]) == "AQo"


def test_premium_hands_rank_high():
    assert rank_hole_cards(["As", "Ad"]) > 0.9
    assert rank_hole_cards(["Kh", "Ks"]) > 0.8
    assert rank_hole_cards(["As", "Ks"]) > 0.6


def test_weak_hands_rank_low():
    r = rank_hole_cards(["7h", "2s"])
    assert r < 0.55, f"72o rank {r} should be < 0.55"
    r = rank_hole_cards(["3c", "2d"])
    assert r < 0.55, f"32o rank {r} should be < 0.55"


def test_preflop_equity():
    assert static_preflop_equity(["As", "Ad"]) > 0.80
    assert static_preflop_equity(["As", "Ks"]) > 0.60
    assert static_preflop_equity(["7h", "2s"]) < 0.40
    assert static_preflop_equity(["As", "Ad"]) > static_preflop_equity(["As", "Ks"])
    assert static_preflop_equity(["As", "Ks"]) > static_preflop_equity(["Ks", "Qs"])


def test_hand_strength_mapping():
    assert hand_strength_from_rank(1) > 0.99
    assert hand_strength_from_rank(7462) < 0.02
    assert 0.25 < hand_strength_from_rank(4000) < 0.55


def test_hand_class_name():
    assert "Full House" in hand_class_name(300) or "Four" in hand_class_name(100)
    assert hand_class_name(7462) == "High Card"


def test_hand_rank_from_hole_class():
    assert hand_rank_from_hole_class(["As", "Ad"]) < hand_rank_from_hole_class(["7h", "2s"])
    assert hand_rank_from_hole_class(["As", "Ks"]) < hand_rank_from_hole_class(["Qc", "Js"])


def test_empty_hole():
    assert _hand_class([]) == ""
    assert rank_hole_cards([]) == 0.45


if __name__ == "__main__":
    test_hand_class_pairs()
    test_hand_class_suited()
    test_hand_class_offsuit()
    test_hand_class_ordering()
    test_premium_hands_rank_high()
    test_weak_hands_rank_low()
    test_preflop_equity()
    test_hand_strength_mapping()
    test_hand_class_name()
    test_hand_rank_from_hole_class()
    test_empty_hole()
    print("All hand_evaluator tests passed!")
