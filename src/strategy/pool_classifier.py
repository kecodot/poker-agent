"""Opponent pool classifier — categorizes table dynamics before each hand.

Classifies the table as Passive / Aggressive / Mixed based on:
- Opponent archetype distribution (from OpponentModel or known bot types)
- Average VPIP, aggression factor, 3bet frequency, fold-to-cbet
- Bot type mapping (for simulation/validation)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PoolClassification:
    pool_type: str          # "passive" | "aggressive" | "mixed"
    confidence: float       # 0.0-1.0
    reasoning: str          # human-readable explanation
    opponent_types: dict[str, str] = field(default_factory=dict)  # seat → archetype/bot_type
    avg_vpip: float = 0.0
    avg_af: float = 0.0
    passive_count: int = 0
    aggressive_count: int = 0
    unknown_count: int = 0


# Bot type → archetype mapping for simulation
BOT_TYPE_MAP = {
    "NitBot": "Nit",
    "CallingStationBot": "Calling Station",
    "TAGBot": "TAG",
    "LAGBot": "LAG",
    "ManiacBot": "Maniac",
    "RandomBot": "Unknown",
    "MonteCarloBot": "TAG",  # Plays TAG-like
}

# Bot type → pool category
BOT_POOL_MAP = {
    "NitBot": "passive",
    "CallingStationBot": "passive",
    "TAGBot": "mixed",
    "LAGBot": "aggressive",
    "ManiacBot": "aggressive",
    "RandomBot": "mixed",
    "MonteCarloBot": "mixed",
}

# Archetype → pool category
ARCHETYPE_POOL_MAP = {
    "Nit": "passive",
    "Calling Station": "passive",
    "Whale": "passive",
    "Passive Fish": "passive",
    "TAG": "mixed",
    "Unknown": "mixed",
    "LAG": "aggressive",
    "Maniac": "aggressive",
}


def classify_from_archetypes(
    opponent_archetypes: dict[str, str],
    opponent_bot_types: dict[str, str] = None,
) -> PoolClassification:
    """Classify table pool from opponent archetypes or bot types.

    Args:
        opponent_archetypes: seat → archetype (e.g., {"2": "LAG"})
        opponent_bot_types: seat → bot_type_name (e.g., {"2": "CallingStationBot"})
            Used in simulation where we know the exact bot type.

    Returns PoolClassification with pool_type and confidence.
    """
    if opponent_bot_types is None:
        opponent_bot_types = {}

    pool_categories: dict[str, int] = {"passive": 0, "aggressive": 0, "mixed": 0}
    classified = 0
    total_opponents = 0
    opponent_details: dict[str, str] = {}

    # Use bot types if available (more accurate in simulation)
    for seat, bot_type in opponent_bot_types.items():
        total_opponents += 1
        pool_cat = BOT_POOL_MAP.get(bot_type, "mixed")
        pool_categories[pool_cat] += 1
        classified += 1
        opponent_details[seat] = bot_type

    # Fill in from archetypes for any remaining opponents
    for seat, arch in opponent_archetypes.items():
        if seat in opponent_details:
            continue
        total_opponents += 1
        pool_cat = ARCHETYPE_POOL_MAP.get(arch, "mixed")
        pool_categories[pool_cat] += 1
        classified += 1
        opponent_details[seat] = arch

    if total_opponents == 0:
        return PoolClassification(
            pool_type="mixed",
            confidence=0.3,
            reasoning="no opponent data available, defaulting to mixed",
            opponent_types={},
        )

    # Determine pool type with confidence
    passive_pct = pool_categories["passive"] / total_opponents
    aggressive_pct = pool_categories["aggressive"] / total_opponents
    mixed_pct = pool_categories["mixed"] / total_opponents

    if passive_pct >= 0.6:
        pool_type = "passive"
        confidence = min(0.95, 0.6 + passive_pct * 0.4)
        reasoning = f"{passive_pct:.0%} passive opponents"
    elif aggressive_pct >= 0.6:
        pool_type = "aggressive"
        confidence = min(0.95, 0.6 + aggressive_pct * 0.4)
        reasoning = f"{aggressive_pct:.0%} aggressive opponents"
    elif passive_pct > aggressive_pct:
        pool_type = "mixed"
        # Mixed leans passive
        confidence = 0.5 + (passive_pct - aggressive_pct) * 0.5
        reasoning = f"mixed table, lean passive ({passive_pct:.0%} passive)"
    elif aggressive_pct > passive_pct:
        pool_type = "mixed"
        confidence = 0.5 + (aggressive_pct - passive_pct) * 0.5
        reasoning = f"mixed table, lean aggressive ({aggressive_pct:.0%} aggressive)"
    else:
        pool_type = "mixed"
        confidence = 0.5
        reasoning = "balanced mixed table"

    return PoolClassification(
        pool_type=pool_type,
        confidence=confidence,
        reasoning=reasoning,
        opponent_types=opponent_details,
        passive_count=pool_categories["passive"],
        aggressive_count=pool_categories["aggressive"],
        unknown_count=total_opponents - classified,
    )


def classify_from_stats(
    avg_vpip: float,
    avg_pfr: float,
    avg_af: float,
    avg_3bet: float = 0.0,
    avg_fold_to_cbet: float = 0.0,
) -> str:
    """Classify pool from aggregate stats (used when archetypes unavailable).

    Returns: 'passive' | 'aggressive' | 'mixed'
    """
    # High VPIP + low PFR = passive calling station pool
    if avg_vpip > 0.35 and avg_pfr < 0.15:
        return "passive"
    if avg_vpip > 0.30 and avg_af < 1.2:
        return "passive"

    # High PFR + high AF = aggressive pool
    if avg_pfr > 0.20 and avg_af > 2.5:
        return "aggressive"
    if avg_3bet > 0.08 and avg_af > 2.0:
        return "aggressive"

    # Low fold-to-cbet + high VPIP = station pool
    if avg_fold_to_cbet < 0.30 and avg_vpip > 0.30:
        return "passive"

    # High fold-to-cbet = exploitable by aggression
    if avg_fold_to_cbet > 0.55:
        return "aggressive"

    return "mixed"
