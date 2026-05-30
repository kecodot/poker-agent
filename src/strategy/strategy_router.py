"""Strategy Router — adaptive strategy selection based on opponent pool.

Routes decisions to the appropriate strategy:
- Passive pool → LimpValue (exploit calling stations with cheap flops + light calls)
- Aggressive pool → RaiseExploit (isolate LAGs with aggressive raising)
- Mixed pool → Hybrid (balanced approach)

Includes BTN-specific overrides to ensure BTN is always a profit center.
"""

from __future__ import annotations

from typing import Optional

from .pool_classifier import (
    classify_from_archetypes,
    PoolClassification,
    BOT_POOL_MAP,
    BOT_TYPE_MAP,
)

# Strategy mode constants
MODE_LIMP_VALUE = "limp_value"
MODE_RAISE_EXPLOIT = "raise_exploit"
MODE_HYBRID = "hybrid"


def select_strategy_mode(
    pool: PoolClassification,
    self_position: str,
    stack_depth_bb: float = 100.0,
) -> str:
    """Select the optimal strategy mode for the current table and position.

    BTN-specific override (Task 4):
    - Passive pool BTN → limp_value (cheap flops, call down = +28 BB/100)
    - Aggressive pool BTN → raise_exploit (isolate = higher fold equity)
    - Mixed pool BTN → hybrid (balanced)

    BB-specific:
    - Passive pool BB → limp_value (check option, defend cheap)
    - Aggressive pool BB → raise_exploit (3bet wider, defend tighter)
    """
    pool_type = pool.pool_type

    # BTN override: must be profit center in ALL modes
    if self_position == "BTN":
        if pool_type == "passive":
            return MODE_LIMP_VALUE
        elif pool_type == "aggressive":
            return MODE_RAISE_EXPLOIT
        else:  # mixed
            return MODE_HYBRID

    # BB: defend strategy varies by pool
    if self_position == "BB":
        if pool_type == "passive":
            return MODE_LIMP_VALUE
        elif pool_type == "aggressive":
            return MODE_RAISE_EXPLOIT
        else:
            return MODE_HYBRID

    # Other positions (SB, UTG, MP, CO)
    if pool_type == "passive":
        return MODE_LIMP_VALUE
    elif pool_type == "aggressive":
        return MODE_RAISE_EXPLOIT
    else:
        return MODE_HYBRID


def classify_and_select(
    opponent_archetypes: dict[str, str],
    opponent_bot_types: dict[str, str],
    self_position: str,
    stack_depth_bb: float = 100.0,
) -> tuple[str, PoolClassification]:
    """Classify the pool and select a strategy mode. One-stop routing call.

    Returns (strategy_mode, pool_classification).
    """
    pool = classify_from_archetypes(opponent_archetypes, opponent_bot_types)
    mode = select_strategy_mode(pool, self_position, stack_depth_bb)
    return mode, pool


# ─── Street-level routing functions ────────────────────────────────────

def route_preflop(
    mode: str,
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str],
    stack_depth_bb: float,
    self_position: str,
):
    """Route preflop decision to the appropriate strategy module."""
    if mode == MODE_LIMP_VALUE:
        from .limp_value import decide_preflop_limp_value
        return decide_preflop_limp_value(
            hole, table, opponent_archetypes, stack_depth_bb, self_position
        )
    elif mode == MODE_HYBRID:
        from .hybrid import decide_preflop_hybrid
        return decide_preflop_hybrid(
            hole, table, opponent_archetypes, stack_depth_bb, self_position
        )
    else:  # raise_exploit (default)
        from .preflop import decide_preflop
        return decide_preflop(
            hole, table, opponent_archetypes, stack_depth_bb, self_position
        )


def route_flop(
    mode: str,
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str],
    stack_depth_bb: float,
    self_position: str,
    is_aggressor: bool,
):
    """Route flop decision to the appropriate strategy module."""
    if mode == MODE_LIMP_VALUE:
        from .limp_value import decide_flop_limp_value
        return decide_flop_limp_value(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
    elif mode == MODE_HYBRID:
        from .hybrid import decide_flop_hybrid
        return decide_flop_hybrid(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
    else:  # raise_exploit
        from .flop import decide_flop
        return decide_flop(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )


def route_turn(
    mode: str,
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str],
    stack_depth_bb: float,
    self_position: str,
    is_aggressor: bool,
):
    """Route turn decision to the appropriate strategy module."""
    if mode == MODE_LIMP_VALUE:
        from .limp_value import decide_turn_limp_value
        return decide_turn_limp_value(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
    elif mode == MODE_HYBRID:
        from .hybrid import decide_turn_hybrid
        return decide_turn_hybrid(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
    else:  # raise_exploit
        from .turn import decide_turn
        return decide_turn(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )


def route_river(
    mode: str,
    hole: list[str],
    table: dict,
    opponent_archetypes: dict[str, str],
    stack_depth_bb: float,
    self_position: str,
    is_aggressor: bool,
):
    """Route river decision to the appropriate strategy module."""
    if mode == MODE_LIMP_VALUE:
        from .limp_value import decide_river_limp_value
        return decide_river_limp_value(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
    elif mode == MODE_HYBRID:
        from .hybrid import decide_river_hybrid
        return decide_river_hybrid(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
    else:  # raise_exploit
        from .river import decide_river
        return decide_river(
            hole, table, opponent_archetypes, stack_depth_bb,
            self_position, is_aggressor
        )
