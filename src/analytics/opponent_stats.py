"""Opponent stats analysis and reporting.

Analyzes opponent behavior patterns to:
  - Identify exploitable tendencies
  - Track stats over time (VPIP/PFR convergence)
  - Generate HUD-like summaries
  - Detect adjustments in opponent play
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from ..engine.opponent_model import OpponentModel, OpponentStats


class OpponentAnalyzer:
    """Analyze opponent stats to find exploitable patterns."""

    def __init__(self, opponent_model: OpponentModel):
        self.model = opponent_model

    def get_table_summary(self, seat_agent_ids: dict[int, str]) -> str:
        """Generate a short text summary of opponents at the table."""
        parts: list[str] = []
        for seat, agent_id in seat_agent_ids.items():
            stats = self.model.get(agent_id)
            if stats and stats.total_hands >= 5:
                parts.append(
                    f"S{seat}({stats.archetype[:3]} "
                    f"VP{stats.vpip:.0%}/PF{stats.pfr:.0%}/"
                    f"3B{stats.three_bet_pct:.0%})"
                )
            else:
                parts.append(f"S{seat}(?)")
        return " | ".join(parts) if parts else "no data"

    def find_most_exploitable(self, min_hands: int = 10) -> list[dict]:
        """Find the most exploitable opponents at the table.

        Returns list of (agent_id, pattern, suggestion).
        """
        results = []
        for agent_id, stats in self.model.players.items():
            if stats.total_hands < min_hands:
                continue

            patterns = []

            # Over-folds to cbets
            if stats.fold_to_cbet_pct > 0.65 and stats.fold_to_cbet_opps >= 5:
                patterns.append({
                    "pattern": "over_folds_to_cbet",
                    "value": stats.fold_to_cbet_pct,
                    "suggestion": "cbet 100% of flops vs this player",
                    "confidence": min(0.9, stats.fold_to_cbet_opps / 10),
                })

            # Over-folds to 3bets
            if stats.fold_to_3bet_pct > 0.70 and stats.fold_to_3bet_opps >= 5:
                patterns.append({
                    "pattern": "over_folds_to_3bet",
                    "value": stats.fold_to_3bet_pct,
                    "suggestion": "3bet wide for folds preflop",
                    "confidence": min(0.9, stats.fold_to_3bet_opps / 10),
                })

            # Too passive (high VPIP, low PFR)
            if stats.vpip > 0.30 and stats.pfr < 0.15 and stats.total_hands >= 10:
                patterns.append({
                    "pattern": "passive_caller",
                    "value": f"VPIP={stats.vpip:.0%}/PFR={stats.pfr:.0%}",
                    "suggestion": "value bet thin, never bluff",
                    "confidence": min(0.85, stats.total_hands / 20),
                })

            # Maniac (over-aggressive)
            if stats.archetype == "Maniac" and stats.total_hands >= 10:
                patterns.append({
                    "pattern": "maniac",
                    "value": f"AF={stats.aggression_factor:.1f}",
                    "suggestion": "trap with strong hands, call down lighter",
                    "confidence": min(0.85, stats.total_hands / 15),
                })

            # Nit (too tight)
            if stats.archetype == "Nit" and stats.total_hands >= 10:
                patterns.append({
                    "pattern": "nit",
                    "value": f"VPIP={stats.vpip:.0%}",
                    "suggestion": "steal blinds relentlessly, fold to aggression",
                    "confidence": min(0.85, stats.total_hands / 15),
                })

            for p in patterns:
                results.append({
                    "agent_id": agent_id,
                    "handle": stats.handle,
                    **p,
                })

        return sorted(results, key=lambda x: x["confidence"], reverse=True)

    def generate_hud_data(self, agent_id: str) -> dict:
        """Generate HUD-like data for a specific opponent."""
        stats = self.model.get(agent_id)
        if not stats:
            return {"agent_id": agent_id, "hands": 0, "status": "no_data"}

        return {
            "agent_id": agent_id,
            "handle": stats.handle,
            "hands": stats.total_hands,
            "archetype": stats.archetype,
            "stats": {
                "VPIP": f"{stats.vpip:.0%}",
                "PFR": f"{stats.pfr:.0%}",
                "3BET": f"{stats.three_bet_pct:.0%}",
                "FCB": f"{stats.fold_to_cbet_pct:.0%}",
                "AF": f"{stats.aggression_factor:.1f}",
            },
            "tendencies": {
                "preflop": self._preflop_tendency(stats),
                "vs_cbet": stats.fold_to_cbet_category,
                "aggression": self._aggression_tendency(stats),
            },
        }

    def _preflop_tendency(self, stats: OpponentStats) -> str:
        if stats.total_hands < 5:
            return "unknown"
        if stats.vpip > 0.35:
            return "loose"
        if stats.vpip < 0.15:
            return "tight"
        return "balanced"

    def _aggression_tendency(self, stats: OpponentStats) -> str:
        if stats.total_hands < 5:
            return "unknown"
        af = stats.aggression_factor
        if af > 4.0:
            return "very_aggressive"
        if af > 2.5:
            return "aggressive"
        if af < 1.0:
            return "passive"
        return "balanced"

    def report(self) -> str:
        """Generate a formatted report of all opponent data."""
        lines = ["=" * 50, "OPPONENT ANALYSIS REPORT",
                  f"Generated: {datetime.now(timezone.utc).isoformat()}",
                  "=" * 50, ""]

        for agent_id, stats in sorted(self.model.players.items(),
                                       key=lambda x: x[1].total_hands, reverse=True):
            if stats.total_hands == 0:
                continue
            lines += [
                f"Player: {stats.handle or agent_id}",
                f"  Hands: {stats.total_hands}",
                f"  VPIP/PFR/3B: {stats.vpip:.0%}/{stats.pfr:.0%}/{stats.three_bet_pct:.0%}",
                f"  FCB/AF: {stats.fold_to_cbet_pct:.0%}/{stats.aggression_factor:.1f}",
                f"  Archetype: {stats.archetype}",
                f"  Showdowns: {stats.showdowns} (won {stats.showdown_wins})",
                "",
            ]

        exploitable = self.find_most_exploitable()
        if exploitable:
            lines += ["─" * 50, "EXPLOITABLE PATTERNS", "─" * 50]
            for e in exploitable[:5]:
                lines.append(
                    f"  {e['agent_id'][:12]}: {e['pattern']} → {e['suggestion']}"
                    f" ({e['confidence']:.0%})"
                )

        return "\n".join(lines)
