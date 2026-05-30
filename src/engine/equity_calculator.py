"""Equity calculator — aggregates Monte Carlo results with pot odds analysis.

Computes:
  - Hand equity vs range
  - Pot odds and required equity
  - SPR (Stack-to-Pot Ratio)
  - Implied odds estimation
  - Fold equity estimation
"""

from __future__ import annotations

from typing import Optional

from .hand_evaluator import static_preflop_equity, hand_strength_from_rank, evaluate_hand, _hand_class
from .monte_carlo import run_monte_carlo, dynamic_sim_count


def compute_pot_odds(call_chips: int, pot_chips: int) -> float:
    """Calculate pot odds as a percentage.

    pot_odds = call / (pot + call)
    E.g., pot=100, call=50 => pot_odds = 50/150 = 0.333
    """
    call_chips = max(0, call_chips)
    pot_chips = max(0, pot_chips)
    if call_chips == 0:
        return 0.0
    return call_chips / (pot_chips + call_chips)


def compute_required_equity(call_chips: int, pot_chips: int) -> float:
    """Minimum equity needed to profitably call. Same as pot_odds in fractional form."""
    return compute_pot_odds(call_chips, pot_chips)


def compute_spr(effective_stack: int, pot_chips: int) -> float:
    """Stack-to-Pot Ratio. Lower SPR favors made hands; higher SPR favors drawing hands."""
    if pot_chips <= 0:
        return 999.0
    return effective_stack / pot_chips


def compute_implied_odds(
    call_chips: int,
    pot_chips: int,
    effective_stack: int,
    equity: float,
    street: str,
) -> float:
    """Estimate implied odds — the extra chips we might win if we hit.

    Returns a multiplier to the direct pot odds.
    >1.0 means we can call wider because of implied odds."""
    if call_chips == 0:
        return 1.0

    pot_odds = compute_pot_odds(call_chips, pot_chips)

    # Estimate how much more we can extract
    remaining_streets = {"Preflop": 3, "Flop": 2, "Turn": 1, "River": 0}
    streets_left = remaining_streets.get(street, 1)

    if streets_left == 0:
        return 1.0

    # Rough implied odds model:
    # On earlier streets, we can extract more value
    max_extract = min(effective_stack, pot_chips * (0.5 * streets_left))
    implied_pot = pot_chips + max_extract * 0.4

    implied_odds = call_chips / max(implied_pot + call_chips, 1)
    return pot_odds / max(implied_odds, 0.001)


def compute_fold_equity(
    bet_size: int,
    pot_chips: int,
    opponent_fold_pct: float,
) -> float:
    """Estimate fold equity from a bet.

    fold_equity = opponent_fold% * pot_size
    Returns EV contribution in chips."""
    if opponent_fold_pct <= 0:
        return 0.0
    return opponent_fold_pct * pot_chips


def should_draw(
    equity: float,
    pot_odds: float,
    implied_odds_mult: float = 1.0,
    position_advantage: float = 0.0,
) -> bool:
    """Decide if we should continue with a drawing hand.

    Adjusted for implied odds and position."""
    required = pot_odds / max(implied_odds_mult, 0.5)
    return equity >= required - 0.03 - position_advantage


class EquityResult:
    """Container for full equity analysis."""

    def __init__(
        self,
        equity: float,
        win_pct: float,
        tie_pct: float,
        lose_pct: float,
        pot_odds: float,
        required_eq: float,
        spr: float,
        implied_mult: float,
        fold_eq_chips: float = 0.0,
        sims_used: int = 0,
        source: str = "monte_carlo",
    ):
        self.equity = equity
        self.win_pct = win_pct
        self.tie_pct = tie_pct
        self.lose_pct = lose_pct
        self.pot_odds = pot_odds
        self.required_equity = required_eq
        self.spr = spr
        self.implied_odds_mult = implied_mult
        self.fold_equity_chips = fold_eq_chips
        self.sims_used = sims_used
        self.source = source

    @property
    def has_direct_odds(self) -> bool:
        return self.equity >= self.pot_odds

    @property
    def has_implied_odds(self) -> bool:
        return self.equity >= self.pot_odds / max(self.implied_odds_mult, 0.5)

    @property
    def equity_edge(self) -> float:
        """How much our equity exceeds required."""
        return self.equity - self.required_equity

    def to_dict(self) -> dict:
        return {
            "equity": self.equity,
            "win_pct": self.win_pct,
            "tie_pct": self.tie_pct,
            "lose_pct": self.lose_pct,
            "pot_odds": self.pot_odds,
            "required_equity": self.required_equity,
            "spr": self.spr,
            "implied_odds_mult": self.implied_odds_mult,
            "fold_equity_chips": self.fold_equity_chips,
            "sims_used": self.sims_used,
            "source": self.source,
        }


def compute_full_equity(
    hole: list[str],
    board: list[str],
    pot_chips: int,
    call_chips: int,
    effective_stack: int,
    n_opponents: int = 1,
    street: str = "Preflop",
    opponent_fold_pct: float = 0.0,
    bet_size: int = 0,
    deadline_ms: float = 300.0,
) -> EquityResult:
    """Compute complete equity analysis for a decision.

    This is the main entry point used by the decision engine.
    """
    # Compute pot odds
    pot_odds = compute_pot_odds(call_chips, pot_chips)

    # Get hand equity
    if not board and len(hole) == 2:
        # Preflop: use static equity table (fast and accurate)
        equity = static_preflop_equity(hole)
        win_pct = equity - 0.03
        tie_pct = 0.06
        lose_pct = 1.0 - equity - 0.03
        sims_used = 0
        source = "static_table"
    else:
        # Postflop: run Monte Carlo
        sims = dynamic_sim_count(hole, board, max_sims=2000, min_sims=200)
        try:
            result = run_monte_carlo(
                hole, board, n_opponents=n_opponents, sims=sims, deadline_ms=deadline_ms
            )
        except Exception:
            result = {"equity": 0.5, "win_pct": 0.45, "tie_pct": 0.1,
                      "lose_pct": 0.45, "sims_completed": 0}
        equity = result["equity"]
        win_pct = result["win_pct"]
        tie_pct = result["tie_pct"]
        lose_pct = result["lose_pct"]
        sims_used = result["sims_completed"]
        source = "monte_carlo"

    # Compute SPR
    spr = compute_spr(effective_stack, pot_chips)

    # Compute implied odds
    implied_mult = compute_implied_odds(
        call_chips, pot_chips, effective_stack, equity, street
    )

    # Compute fold equity if betting
    fold_eq = 0.0
    if bet_size > 0 and opponent_fold_pct > 0:
        fold_eq = compute_fold_equity(bet_size, pot_chips, opponent_fold_pct)

    return EquityResult(
        equity=round(equity, 4),
        win_pct=round(win_pct, 4),
        tie_pct=round(tie_pct, 4),
        lose_pct=round(lose_pct, 4),
        pot_odds=round(pot_odds, 4),
        required_eq=round(pot_odds, 4),
        spr=round(spr, 1),
        implied_mult=round(implied_mult, 2),
        fold_eq_chips=round(fold_eq, 1),
        sims_used=sims_used,
        source=source,
    )


def quick_equity(hole: list[str], board: list[str]) -> float:
    """Fast equity estimate without full analysis. Returns 0.0-1.0."""
    if not board:
        return static_preflop_equity(hole)
    result = run_monte_carlo(hole, board, n_opponents=1, sims=500, deadline_ms=100)
    return result["equity"]
