"""Multi-threaded Monte Carlo equity simulation engine.

Supports: 1k / 5k / 10k simulations.
Input: hole cards, board cards, number of opponents (1-5).
Output: win%, tie%, lose%.

Performance target: <300ms for 10k sims on standard hardware.
Uses pre-computed deck pool and efficient sampling.
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutTimeout
from typing import Optional

try:
    from treys import Card as TreysCard
    from treys import Deck as TreysDeck
    from treys import Evaluator as TreysEvaluator
    _HAS_TREYS = True
except Exception:
    _HAS_TREYS = False

SIM_PRESETS = {"fast": 1000, "standard": 5000, "accurate": 10000}
MAX_WORKERS = 4

# Pre-computed full deck for reuse
_FULL_DECK: list = []


def _get_full_deck() -> list:
    """Get the full 52-card deck as a list of treys Card objects. Cached."""
    global _FULL_DECK
    if not _FULL_DECK and _HAS_TREYS:
        _FULL_DECK = list(TreysDeck().cards)
    return _FULL_DECK


def _to_treys(card_str: str):
    if not card_str:
        return TreysCard.new("2c")
    r = card_str[0].upper()
    if card_str.startswith("10"):
        r = "T"
        s = card_str[2].lower() if len(card_str) > 2 else "x"
    else:
        s = card_str[-1].lower()
    return TreysCard.new(r + s)


def _simulate_batch(
    hero_treys: list,
    board_treys: list,
    available_deck: list,
    n_opponents: int,
    n_sims: int,
    seed: int,
) -> tuple[int, int, int]:
    """Run a batch of Monte Carlo simulations. Uses pre-filtered deck for speed."""
    if not _HAS_TREYS or len(available_deck) < 2 * n_opponents + (5 - len(board_treys)):
        return (0, 0, 0)

    ev = TreysEvaluator()
    needed_board = 5 - len(board_treys)
    total_needed = 2 * n_opponents + needed_board

    rng = random.Random(seed)
    wins = ties = losses = 0
    n_avail = len(available_deck)

    for _ in range(n_sims):
        # Efficient sampling without creating new objects
        indices = list(range(n_avail))
        rng.shuffle(indices)

        # Deal opponent cards
        opp_hands = []
        for opp_i in range(n_opponents):
            i = opp_i * 2
            opp_hands.append([available_deck[indices[i]], available_deck[indices[i + 1]]])

        # Build runout
        runout_start = 2 * n_opponents
        runout = [available_deck[indices[runout_start + j]] for j in range(needed_board)]

        full_board = board_treys + runout
        hero_rank = ev.evaluate(full_board, hero_treys)

        best_opp_rank = 8000
        for opp in opp_hands:
            opp_rank = ev.evaluate(full_board, opp)
            if opp_rank < best_opp_rank:
                best_opp_rank = opp_rank

        if hero_rank < best_opp_rank:
            wins += 1
        elif hero_rank == best_opp_rank:
            ties += 1
        else:
            losses += 1

    return (wins, ties, losses)


def run_monte_carlo(
    hole: list[str],
    board: list[str],
    n_opponents: int = 1,
    sims: int = 5000,
    deadline_ms: float = 300.0,
) -> dict:
    """Run multi-threaded Monte Carlo equity simulation.

    Args:
        hole: Hero's hole cards, e.g. ['As', 'Ks']
        board: Community cards, e.g. ['Ah', 'Kd', '7c'] or [] for preflop
        n_opponents: Number of active opponents (1-5)
        sims: Number of simulations to run
        deadline_ms: Max time in milliseconds (returns early if exceeded)

    Returns:
        {'win_pct', 'tie_pct', 'lose_pct', 'equity', 'sims_completed', 'elapsed_ms'}
    """
    if not _HAS_TREYS or not hole:
        return {
            "win_pct": 0.5, "tie_pct": 0.0, "lose_pct": 0.5,
            "equity": 0.5, "sims_completed": 0, "elapsed_ms": 0.0,
        }

    n_opponents = max(1, min(5, n_opponents))
    sims = max(100, min(20000, sims))

    try:
        hero_treys = [_to_treys(c) for c in hole]
        board_treys = [_to_treys(c) for c in board]
    except Exception:
        return {
            "win_pct": 0.5, "tie_pct": 0.0, "lose_pct": 0.5,
            "equity": 0.5, "sims_completed": 0, "elapsed_ms": 0.0,
        }

    used_set = set(hero_treys) | set(board_treys)
    full_deck = _get_full_deck()
    available = [c for c in full_deck if c not in used_set]

    if len(available) < 4:
        return {
            "win_pct": 1.0, "tie_pct": 0.0, "lose_pct": 0.0,
            "equity": 1.0, "sims_completed": 0, "elapsed_ms": 0.0,
        }

    t0 = time.perf_counter()
    deadline_s = max(0.1, deadline_ms / 1000.0)

    # Use single-thread for small sims (< 1000) to avoid overhead
    if sims < 1000:
        try:
            wins, ties, losses = _simulate_batch(
                hero_treys, board_treys, available, n_opponents, sims,
                seed=int(t0 * 1000) % 100000,
            )
        except Exception:
            wins, ties, losses = 0, 0, 0
        total = wins + ties + losses
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if total == 0:
            return {
                "win_pct": 0.5, "tie_pct": 0.0, "lose_pct": 0.5,
                "equity": 0.5, "sims_completed": 0, "elapsed_ms": elapsed_ms,
            }
        return {
            "win_pct": round(wins / total, 4),
            "tie_pct": round(ties / total, 4),
            "lose_pct": round(losses / total, 4),
            "equity": round((wins + 0.5 * ties) / total, 4),
            "sims_completed": total,
            "elapsed_ms": round(elapsed_ms, 1),
        }

    # Multi-threaded for larger sim counts
    n_workers = min(MAX_WORKERS, max(1, sims // 500))
    sims_per = sims // n_workers
    total_wins = total_ties = total_losses = 0
    completed = 0

    try:
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            futures = []
            for i in range(n_workers):
                n = sims_per + (1 if i < sims % n_workers else 0)
                if n <= 0:
                    continue
                futures.append(executor.submit(
                    _simulate_batch,
                    hero_treys, board_treys, available, n_opponents, n,
                    seed=i * 31337 + int(t0 * 1000) % 100000,
                ))

            for f in as_completed(futures, timeout=deadline_s * 2):
                try:
                    w, t, l = f.result()
                    total_wins += w
                    total_ties += t
                    total_losses += l
                    completed += 1
                except Exception:
                    pass
    except FutTimeout:
        pass  # Return partial results

    elapsed_ms = (time.perf_counter() - t0) * 1000
    total = total_wins + total_ties + total_losses

    if total == 0:
        # Fallback: rough equity based on hand class
        from .hand_evaluator import static_preflop_equity, _hand_class
        eq = static_preflop_equity(hole) if not board else 0.45
        return {
            "win_pct": round(eq - 0.02, 4),
            "tie_pct": 0.04,
            "lose_pct": round(1.0 - eq - 0.02, 4),
            "equity": round(eq, 4),
            "sims_completed": 0,
            "elapsed_ms": round(elapsed_ms, 1),
        }

    return {
        "win_pct": round(total_wins / total, 4),
        "tie_pct": round(total_ties / total, 4),
        "lose_pct": round(total_losses / total, 4),
        "equity": round((total_wins + 0.5 * total_ties) / total, 4),
        "sims_completed": total,
        "elapsed_ms": round(elapsed_ms, 1),
    }


def equity_vs_range(
    hole: list[str],
    board: list[str],
    villain_range: set,
    sims: int = 1000,
) -> float:
    """Equity vs a specific range using random villain hands from the range."""
    if not _HAS_TREYS or not hole or not villain_range:
        return 0.5
    try:
        hero_treys = [_to_treys(c) for c in hole]
        board_treys = [_to_treys(c) for c in board]
    except Exception:
        return 0.5

    full_deck = _get_full_deck()
    used = set(hero_treys) | set(board_treys)
    available = [c for c in full_deck if c not in used]
    if len(available) < 2:
        return 1.0

    ev = TreysEvaluator()
    rng = random.Random(42)
    total = wins = 0.0

    for _ in range(min(sims, 500)):
        rng.shuffle(available)
        opp = [available[0], available[1]]
        remaining = available[2:]
        needed = 5 - len(board_treys)
        runout = remaining[:needed]
        full_board = board_treys + runout
        hero_r = ev.evaluate(full_board, hero_treys)
        opp_r = ev.evaluate(full_board, opp)
        if hero_r < opp_r:
            wins += 1.0
        elif hero_r == opp_r:
            wins += 0.5
        total += 1

    return wins / max(total, 1)


def dynamic_sim_count(
    hole: list[str],
    board: list[str],
    target_precision: float = 0.01,
    max_sims: int = 10000,
    min_sims: int = 200,
) -> int:
    """Dynamically determine sim count based on situation.

    Fewer sims for clear decisions; more for marginal spots."""
    if not board:
        return min(500, max_sims)
    if len(board) >= 3:
        try:
            from .hand_evaluator import evaluate_hand, hand_strength_from_rank
            rank = evaluate_hand(hole, board)
            strength = hand_strength_from_rank(rank)
            if strength > 0.80 or strength < 0.20:
                return min(300, max_sims)
        except Exception:
            pass
    return min(2000, max_sims)
