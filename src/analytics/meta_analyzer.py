"""Arena Meta Analyzer — player pool analysis and meta-game insights.

Answers:
  - Most common player type in the arena
  - Most profitable play style
  - Which positions are most/least profitable
  - Which hand types lose the most money

Generates: meta-report.md
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class MetaAnalyzer:
    """Analyze the player pool meta-game from hand history data."""

    def __init__(self, db=None, output_dir: str = "reports"):
        self.db = db
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_db(self, db):
        self.db = db

    def _require_db(self):
        if self.db is None:
            raise RuntimeError("MetaAnalyzer: no database set.")

    def analyze(self) -> dict:
        """Run full meta analysis."""
        self._require_db()
        opponents = self.db.get_all_opponents(min_hands=1)
        hands = self.db.get_recent_hands(10000)

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "player_pool": self._analyze_player_pool(opponents),
            "profitability": self._analyze_profitability(hands),
            "position_analysis": self._analyze_positions(),
            "hand_type_analysis": self._analyze_hand_types(hands),
            "meta_insights": [],  # filled below
        }

    def _analyze_player_pool(self, opponents: list[dict]) -> dict:
        """Break down the player pool by archetype."""
        archetypes = Counter()
        total = len(opponents)

        for o in opponents:
            arch = o.get("archetype", "Unknown")
            archetypes[arch] += 1

        distribution = {}
        for arch, count in archetypes.most_common():
            distribution[arch] = {
                "count": count,
                "pct": round(count / max(total, 1) * 100, 1),
            }

        dominant = archetypes.most_common(1)
        dominant_type = dominant[0][0] if dominant else "Unknown"
        dominant_pct = round(dominant[0][1] / max(total, 1) * 100, 1) if dominant else 0

        return {
            "total_players": total,
            "archetype_distribution": distribution,
            "dominant_type": dominant_type,
            "dominant_pct": dominant_pct,
        }

    def _analyze_profitability(self, hands: list[dict]) -> dict:
        """Analyze what's making/losing money."""
        if not hands:
            return {"hands": 0, "message": "no data"}

        total = len(hands)
        winning = [h for h in hands if h.get("chip_delta", 0) > 0]
        losing = [h for h in hands if h.get("chip_delta", 0) < 0]

        total_won = sum(h.get("chip_delta", 0) for h in winning)
        total_lost = sum(h.get("chip_delta", 0) for h in losing)

        # Profit by street
        by_street: dict[str, dict] = {}
        for h in hands:
            st = h.get("street_reached", "Preflop")
            d = by_street.setdefault(st, {"hands": 0, "net": 0, "wins": 0, "losses": 0})
            d["hands"] += 1
            d["net"] += h.get("chip_delta", 0)
            if h.get("chip_delta", 0) > 0:
                d["wins"] += 1
            elif h.get("chip_delta", 0) < 0:
                d["losses"] += 1

        # Most profitable street strategy
        most_profitable = max(by_street.items(),
                            key=lambda x: x[1]["net"] / max(x[1]["hands"], 1),
                            default=("N/A", {"net": 0, "hands": 1}))

        # Biggest loss source
        biggest_loss = min(by_street.items(),
                          key=lambda x: x[1]["net"] / max(x[1]["hands"], 1),
                          default=("N/A", {"net": 0, "hands": 1}))

        return {
            "hands_analyzed": total,
            "total_won": total_won,
            "total_lost": total_lost,
            "net": total_won + total_lost,
            "by_street": {
                st: {
                    "hands": d["hands"],
                    "net": d["net"],
                    "avg": round(d["net"] / max(d["hands"], 1), 1),
                    "win_rate": round(d["wins"] / max(d["hands"], 1), 3),
                }
                for st, d in by_street.items()
            },
            "most_profitable_street": most_profitable[0],
            "biggest_loss_street": biggest_loss[0],
        }

    def _analyze_positions(self) -> dict:
        """Position P&L breakdown."""
        pos_stats = self.db.get_position_stats(10000)
        if not pos_stats:
            return {"positions": {}, "best": "N/A", "worst": "N/A"}

        best_pos = max(pos_stats.items(),
                      key=lambda x: x[1].get("bb_per_100", -999),
                      default=("N/A", {}))
        worst_pos = min(pos_stats.items(),
                       key=lambda x: x[1].get("bb_per_100", 999),
                       default=("N/A", {}))

        return {
            "positions": pos_stats,
            "best_position": best_pos[0],
            "best_bb_per_100": best_pos[1].get("bb_per_100", 0),
            "worst_position": worst_pos[0],
            "worst_bb_per_100": worst_pos[1].get("bb_per_100", 0),
        }

    def _analyze_hand_types(self, hands: list[dict]) -> dict:
        """Analyze which hand types are winning/losing the most."""
        if not hands:
            return {"losing_hands": [], "winning_hands": []}

        # Group hands by hole cards class
        hand_class_pnl: dict[str, dict] = {}
        for h in hands:
            hole = h.get("hole_cards", "[]")
            if isinstance(hole, str):
                hole = json.loads(hole) if hole.startswith("[") else []
            if len(hole) != 2:
                continue

            # Classify hand
            r1, r2 = hole[0][0].upper(), hole[1][0].upper()
            suited = hole[0][1].lower() == hole[1][1].lower() if len(hole[0]) >= 2 and len(hole[1]) >= 2 else False

            rank_order = "AKQJT98765432"
            if rank_order.index(r1) < rank_order.index(r2):
                pair_str = f"{r1}{r2}"
            else:
                pair_str = f"{r2}{r1}"

            if r1 == r2:
                cls = f"{r1}{r2}"
            else:
                cls = f"{pair_str}{'s' if suited else 'o'}"

            d = hand_class_pnl.setdefault(cls, {"hands": 0, "net": 0, "wins": 0, "losses": 0})
            d["hands"] += 1
            d["net"] += h.get("chip_delta", 0)
            if h.get("chip_delta", 0) > 0:
                d["wins"] += 1
            elif h.get("chip_delta", 0) < 0:
                d["losses"] += 1

        # Sort by net chips lost (biggest losers)
        losers = sorted(
            [(cls, d) for cls, d in hand_class_pnl.items() if d["hands"] >= 3 and d["net"] < 0],
            key=lambda x: x[1]["net"]
        )[:10]
        winners = sorted(
            [(cls, d) for cls, d in hand_class_pnl.items() if d["hands"] >= 3 and d["net"] > 0],
            key=lambda x: -x[1]["net"]
        )[:10]

        return {
            "biggest_losers": [
                {"hand": cls, "hands": d["hands"], "net": d["net"],
                 "win_rate": round(d["wins"] / max(d["hands"], 1), 3)}
                for cls, d in losers
            ],
            "biggest_winners": [
                {"hand": cls, "hands": d["hands"], "net": d["net"],
                 "win_rate": round(d["wins"] / max(d["hands"], 1), 3)}
                for cls, d in winners
            ],
        }

    def generate_insights(self, data: dict) -> list[str]:
        """Generate actionable insights from meta analysis data."""
        insights = []

        pool = data.get("player_pool", {})
        profit = data.get("profitability", {})
        positions = data.get("position_analysis", {})
        hand_types = data.get("hand_type_analysis", {})

        # Player pool insight
        dominant = pool.get("dominant_type", "Unknown")
        dominant_pct = pool.get("dominant_pct", 0)
        if dominant_pct > 25:
            if dominant == "Nit":
                insights.append(
                    f"Arena is {dominant_pct}% Nits — steal blinds aggressively and fold to "
                    "their rare 3bets. They over-fold to aggression."
                )
            elif dominant == "TAG":
                insights.append(
                    f"Arena is {dominant_pct}% TAGs — balanced play needed. Exploit by "
                    "attacking their blinds with position."
                )
            elif dominant in ("Calling Station", "Whale"):
                insights.append(
                    f"Arena is {dominant_pct}% loose-passive — value bet relentlessly. "
                    "Never bluff. Extract max value with strong hands."
                )
            elif dominant == "LAG":
                insights.append(
                    f"Arena is {dominant_pct}% LAGs — trap with monsters. Let them "
                    "bluff into you. Call down lighter."
                )
            elif dominant == "Maniac":
                insights.append(
                    f"Arena is {dominant_pct}% Maniacs — play tight, trap with strong "
                    "hands, and let them spew chips."
                )

        # Position insight
        best_pos = positions.get("best_position", "N/A")
        worst_pos = positions.get("worst_position", "N/A")
        worst_bb = positions.get("worst_bb_per_100", 0)

        if worst_pos != "N/A" and worst_bb < -5:
            insights.append(
                f"Biggest leak is from {worst_pos} ({worst_bb:.1f} BB/100). "
                "Tighten range from this position."
            )
        if best_pos != "N/A":
            insights.append(
                f"Most profitable position: {best_pos}. Consider widening range "
                "slightly here when table conditions are favorable."
            )

        # Profitability insight
        best_street = profit.get("most_profitable_street", "N/A")
        worst_street = profit.get("biggest_loss_street", "N/A")

        if worst_street in ("River", "Turn"):
            insights.append(
                f"Losing most money on {worst_street}. Review late-street decisions: "
                "avoid calling down light, value bet thinner, reduce bluffs."
            )
        if best_street == "Preflop":
            insights.append(
                "Preflop is most profitable — solid hand selection and position play "
                "are working. Continue tight-aggressive preflop strategy."
            )

        # Hand type insight
        losers = hand_types.get("biggest_losers", [])
        if losers:
            top_losers = ", ".join(l["hand"] for l in losers[:3])
            insights.append(
                f"Biggest losing hands: {top_losers}. Review how these are played "
                "postflop — may be overvaluing marginal made hands."
            )

        return insights

    def generate_report(self) -> str:
        """Generate formatted markdown meta-report."""
        data = self.analyze()
        data["meta_insights"] = self.generate_insights(data)
        insights = data["meta_insights"]
        pool = data["player_pool"]
        profit = data["profitability"]
        positions = data["position_analysis"]
        hand_types = data["hand_type_analysis"]

        lines = [
            "# Arena Meta Analysis Report",
            f"Generated: {data['timestamp']}",
            f"Players tracked: {pool.get('total_players', 0)}",
            "",
            "---",
            "",
            "## Key Insights",
            "",
        ]
        for i, insight in enumerate(insights, 1):
            lines.append(f"{i}. {insight}")
        if not insights:
            lines.append("Insufficient data for insights — play more hands to populate.")

        lines += [
            "",
            "## Player Pool Composition",
            "",
            f"**Dominant type:** {pool.get('dominant_type', '?')} ({pool.get('dominant_pct', 0)}%)",
            "",
            "| Archetype | Count | % |",
            "|-----------|-------|---|",
        ]
        for arch, info in pool.get("archetype_distribution", {}).items():
            lines.append(f"| {arch} | {info['count']} | {info['pct']}% |")

        lines += [
            "",
            "## Profitability Analysis",
            "",
            f"Hands analyzed: {profit.get('hands_analyzed', 0)}",
            f"Total won: {profit.get('total_won', 0)}",
            f"Total lost: {profit.get('total_lost', 0)}",
            f"Net: {profit.get('net', 0)}",
            "",
            "### By Street",
            "",
            "| Street | Hands | Net | Avg/Hand | Win Rate |",
            "|--------|-------|-----|----------|----------|",
        ]
        for st, info in profit.get("by_street", {}).items():
            lines.append(
                f"| {st} | {info['hands']} | {info['net']} | "
                f"{info['avg']} | {info['win_rate']:.1%} |"
            )

        lines += [
            "",
            "## Position Analysis",
            "",
            "| Position | Hands | Net | BB/100 | Win Rate |",
            "|----------|-------|-----|--------|----------|",
        ]
        for pos, info in positions.get("positions", {}).items():
            lines.append(
                f"| {pos} | {info.get('hands', 0)} | {info.get('net_chips', 0)} | "
                f"{info.get('bb_per_100', 0):.1f} | {info.get('win_rate', 0):.1%} |"
            )

        lines += [
            "",
            "## Hand Type Analysis",
            "",
            "### Biggest Losers",
            "",
            "| Hand | Hands | Net | Win Rate |",
            "|------|-------|-----|----------|",
        ]
        for h in hand_types.get("biggest_losers", []):
            lines.append(
                f"| {h['hand']} | {h['hands']} | {h['net']} | {h['win_rate']:.1%} |"
            )

        lines += [
            "",
            "### Biggest Winners",
            "",
            "| Hand | Hands | Net | Win Rate |",
            "|------|-------|-----|----------|",
        ]
        for h in hand_types.get("biggest_winners", []):
            lines.append(
                f"| {h['hand']} | {h['hands']} | {h['net']} | {h['win_rate']:.1%} |"
            )

        return "\n".join(lines)

    def save_report(self) -> str:
        """Generate and save meta-report.md."""
        report = self.generate_report()
        path = self.output_dir / "meta-report.md"
        path.write_text(report)
        return str(path)
