"""Tests for equity_calculator module."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.engine.equity_calculator import (
    compute_pot_odds,
    compute_required_equity,
    compute_spr,
    compute_implied_odds,
    compute_fold_equity,
    compute_full_equity,
    quick_equity,
    EquityResult,
)


def test_pot_odds():
    assert abs(compute_pot_odds(50, 100) - 0.3333) < 0.01
    assert abs(compute_pot_odds(100, 100) - 0.50) < 0.01
    assert compute_pot_odds(0, 100) == 0.0
    assert compute_pot_odds(10, 0) == 1.0  # Call 10 into 0 pot


def test_required_equity():
    assert abs(compute_required_equity(50, 100) - 0.3333) < 0.01


def test_spr():
    assert compute_spr(200, 100) == 2.0
    assert compute_spr(200, 0) > 99
    assert compute_spr(100, 200) == 0.5


def test_implied_odds():
    # Early street should have implied odds > 1
    imp = compute_implied_odds(10, 20, 200, 0.5, "Flop")
    assert imp > 1.0, f"Flop implied odds should be > 1, got {imp}"

    # River should not have implied odds
    imp_river = compute_implied_odds(10, 20, 200, 0.5, "River")
    assert abs(imp_river - 1.0) < 0.1


def test_fold_equity():
    fe = compute_fold_equity(50, 100, 0.5)
    assert fe == 50.0
    fe = compute_fold_equity(50, 100, 0.0)
    assert fe == 0.0


def test_equity_result():
    r = EquityResult(0.6, 0.55, 0.1, 0.35, 0.33, 0.33, 3.0, 1.5)
    assert r.has_direct_odds
    assert r.has_implied_odds
    assert abs(r.equity_edge - 0.27) < 0.01


def test_full_equity_preflop():
    result = compute_full_equity(
        ["As", "Ad"], [], 3, 2, 200, n_opponents=1, street="Preflop",
    )
    assert result.equity > 0.75, f"AA should have high equity, got {result.equity}"
    assert result.source == "static_table"


def test_quick_equity():
    eq = quick_equity(["As", "Ad"], [])
    assert eq > 0.75, f"AA should have high equity, got {eq}"
    eq = quick_equity(["7h", "2s"], [])
    assert eq < 0.40, f"72o should have low equity, got {eq}"


if __name__ == "__main__":
    test_pot_odds()
    test_required_equity()
    test_spr()
    test_implied_odds()
    test_fold_equity()
    test_equity_result()
    test_full_equity_preflop()
    test_quick_equity()
    print("All equity_calculator tests passed!")
