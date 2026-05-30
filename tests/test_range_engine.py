"""Tests for range_engine module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.range_engine import (
    hand_class,
    seat_to_position,
    is_in_opening_range,
    is_in_3bet_range,
    is_in_4bet_range,
    is_5bet_all_in,
    is_premium,
    is_strong,
    OPENING_RANGES,
    THREE_BET_RANGES,
)


def test_seat_to_position():
    assert seat_to_position(1, 6) == "BTN"
    assert seat_to_position(4, 6) == "UTG"
    assert seat_to_position(6, 6) == "CO"
    assert seat_to_position(5, 6) == "MP"
    assert seat_to_position(2, 6) == "SB"
    assert seat_to_position(3, 6) == "BB"


def test_opening_ranges_premium():
    assert is_in_opening_range(["As", "Ad"], "UTG")
    assert is_in_opening_range(["Kh", "Ks"], "UTG")
    assert is_in_opening_range(["As", "Ks"], "UTG")
    assert is_in_opening_range(["Ah", "Kd"], "UTG")


def test_opening_ranges_not_in_range():
    assert not is_in_opening_range(["7h", "2s"], "UTG")
    assert not is_in_opening_range(["3c", "4d"], "UTG")
    assert not is_in_opening_range(["Ks", "2d"], "UTG")


def test_opening_ranges_broaden_late():
    # BTN should open wider
    assert is_in_opening_range(["8s", "7s"], "BTN")
    assert is_in_opening_range(["Ac", "5c"], "BTN")
    assert is_in_opening_range(["Td", "9d"], "BTN")
    # These should NOT open UTG
    assert not is_in_opening_range(["8s", "7s"], "UTG")


def test_3bet_ranges():
    assert is_in_3bet_range(["As", "Ad"], "UTG")
    assert is_in_3bet_range(["Ah", "Kd"], "BTN")
    assert is_in_3bet_range(["Qs", "Qd"], "CO")


def test_4bet_ranges():
    assert is_in_4bet_range(["As", "Ad"], "BTN")
    assert is_in_4bet_range(["Kh", "Ks"], "MP")
    assert is_in_4bet_range(["As", "Ks"], "CO")


def test_5bet_all_in():
    assert is_5bet_all_in(["As", "Ad"])
    assert is_5bet_all_in(["Kh", "Ks"])
    assert is_5bet_all_in(["As", "Ks"])
    assert not is_5bet_all_in(["Js", "Jd"])


def test_premium():
    assert is_premium(["As", "Ad"])
    assert is_premium(["Kh", "Ks"])
    assert is_premium(["Ah", "Kd"])
    assert not is_premium(["Js", "Jd"])


def test_strong():
    assert is_strong(["As", "Ad"])
    assert is_strong(["Js", "Jd"])
    assert is_strong(["Ah", "Qd"])
    assert not is_strong(["Ts", "9s"])


def test_ranges_complete():
    for pos in ["UTG", "MP", "CO", "BTN", "SB", "BB"]:
        assert len(OPENING_RANGES[pos]) > 0, f"{pos} opening range empty"
        assert len(THREE_BET_RANGES[pos]) > 0, f"{pos} 3bet range empty"


if __name__ == "__main__":
    test_seat_to_position()
    test_opening_ranges_premium()
    test_opening_ranges_not_in_range()
    test_opening_ranges_broaden_late()
    test_3bet_ranges()
    test_4bet_ranges()
    test_5bet_all_in()
    test_premium()
    test_strong()
    test_ranges_complete()
    print("All range_engine tests passed!")
