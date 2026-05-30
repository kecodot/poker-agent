"""Position profitability analyzer — tracks BB/100 by position.

Detects position-based leaks and generates corrective suggestions.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class PositionStats:
    hands: int = 0
    net_chips: int = 0
    wins: int = 0
    losses: int = 0
    vpip_hands: int = 0
    pfr_hands: int = 0


@dataclass
class PositionReport:
    stats: dict[str, PositionStats] = field(default_factory=dict)
    overall_bb_per_100: float = 0.0

    @property
    def best_position(self) -> tuple[str, float]:
        best = ("", -9999.0)
        for pos, s in self.stats.items():
            if s.hands > 0:
                bb100 = (s.net_chips / 2.0) / max(s.hands, 1) * 100
                if bb100 > best[1]:
                    best = (pos, bb100)
        return best

    @property
    def worst_position(self) -> tuple[str, float]:
        worst = ("", 9999.0)
        for pos, s in self.stats.items():
            if s.hands > 0:
                bb100 = (s.net_chips / 2.0) / max(s.hands, 1) * 100
                if bb100 < worst[1]:
                    worst = (pos, bb100)
        return worst

    def leaks(self) -> list[dict]:
        """Identify position-based leaks."""
        results = []
        for pos in ["BTN", "CO", "MP", "UTG", "SB", "BB"]:
            s = self.stats.get(pos)
            if not s or s.hands < 50:
                continue
            bb100 = (s.net_chips / 2.0) / max(s.hands, 1) * 100
            vpip = s.vpip_hands / max(s.hands, 1)
            pfr = s.pfr_hands / max(s.hands, 1)
            pfr_ratio = pfr / max(vpip, 0.01)

            leak = None
            if bb100 < -10:
                leak = {
                    "position": pos,
                    "severity": "critical" if bb100 < -30 else "high",
                    "bb_per_100": round(bb100, 1),
                    "issue": "negative win rate",
                    "suggestion": _suggest_position_fix(pos, bb100, vpip, pfr, pfr_ratio),
                }
            elif pfr_ratio < 0.5 and pos != "BB":
                leak = {
                    "position": pos,
                    "severity": "medium",
                    "bb_per_100": round(bb100, 1),
                    "issue": f"too much limping (PFR/VPIP={pfr_ratio:.1%})",
                    "suggestion": "raise or fold; avoid limping from non-blind positions",
                }
            elif bb100 > 50:
                leak = {
                    "position": pos,
                    "severity": "low",
                    "bb_per_100": round(bb100, 1),
                    "issue": "strong performance",
                    "suggestion": "maintain current strategy",
                }

            if leak:
                results.append(leak)
        return results


def _suggest_position_fix(pos: str, bb100: float, vpip: float, pfr: float, pfr_ratio: float) -> str:
    if pos == "BTN":
        if vpip > 0.5:
            return "tighten BTN opening range; fold bottom 20% of current range"
        if pfr_ratio < 0.5:
            return "raise more from BTN; increase steal frequency"
        return "review postflop strategy from BTN; cbet more on dry boards"
    if pos in ("SB", "BB"):
        return "tighten blind defense; fold weak hands to raises"
    if pos in ("UTG", "MP"):
        return "tighten early position opening range; only play premium hands"
    return "review strategy from this position"


def analyze_positions(hands: list[dict]) -> PositionReport:
    """Analyze position profitability from list of hand results.

    Each hand dict should have: position, chip_delta, vpip, pfr
    """
    report = PositionReport()

    for h in hands:
        pos = h.get("position", "unknown")
        delta = h.get("chip_delta", 0)
        vpip = h.get("vpip", False)
        pfr = h.get("pfr", False)

        s = report.stats.setdefault(pos, PositionStats())
        s.hands += 1
        s.net_chips += delta
        if delta > 0:
            s.wins += 1
        elif delta < 0:
            s.losses += 1
        if vpip:
            s.vpip_hands += 1
        if pfr:
            s.pfr_hands += 1

    total_chips = sum(s.net_chips for s in report.stats.values())
    total_hands = sum(s.hands for s in report.stats.values())
    report.overall_bb_per_100 = (total_chips / 2.0) / max(total_hands, 1) * 100

    return report


def format_report(report: PositionReport) -> str:
    """Format position analysis as markdown."""
    lines = [
        "# Position Profitability Analysis",
        "",
        f"Overall: **{report.overall_bb_per_100:+.1f} BB/100**",
        "",
        "| Position | Hands | BB/100 | Win Rate | VPIP | PFR | Net Chips |",
        "|----------|-------|--------|----------|------|-----|-----------|",
    ]

    for pos in ["BTN", "CO", "MP", "UTG", "SB", "BB"]:
        s = report.stats.get(pos)
        if not s or s.hands == 0:
            continue
        bb100 = (s.net_chips / 2.0) / max(s.hands, 1) * 100
        wr = s.wins / max(s.hands, 1)
        vpip = s.vpip_hands / max(s.hands, 1)
        pfr = s.pfr_hands / max(s.hands, 1)
        lines.append(
            f"| {pos} | {s.hands:,} | {bb100:+.1f} | {wr:.1%} | "
            f"{vpip:.1%} | {pfr:.1%} | {s.net_chips:+,} |"
        )

    lines += [
        "",
        f"**Best position:** {report.best_position[0]} ({report.best_position[1]:+.1f} BB/100)",
        f"**Worst position:** {report.worst_position[0]} ({report.worst_position[1]:+.1f} BB/100)",
        "",
        "## Detected Leaks",
        "",
    ]

    for leak in report.leaks():
        lines.append(f"- **[{leak['severity'].upper()}]** {leak['position']}: "
                     f"{leak['issue']} ({leak['bb_per_100']:+.1f} BB/100) → {leak['suggestion']}")

    return "\n".join(lines)
