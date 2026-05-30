"""Poker Analytics Engine — automated statistics and reporting.

Computes: BB/100, ROI, VPIP, PFR, 3BET, Fold To 3Bet, Fold To CBet,
          WTSD, W$SD, Aggression Factor.

Generates reports for 100, 1000, 10000 hand windows.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AnalyticsEngine:
    """Compute poker statistics from SQLite hand database."""

    def __init__(self, db=None, output_dir: str = "reports"):
        self.db = db
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_db(self, db):
        self.db = db

    def _require_db(self):
        if self.db is None:
            raise RuntimeError("AnalyticsEngine: no database set. Call set_db() first.")

    def compute_basic_stats(self, n: int = 100) -> dict:
        """Compute basic stats for last N hands: BB/100, win rate, VPIP, PFR."""
        self._require_db()
        hands = self.db.get_recent_hands(n)
        if not hands:
            return {"hands": 0, "message": "no data"}

        total = len(hands)
        wins = sum(1 for h in hands if h.get("chip_delta", 0) > 0)
        losses = sum(1 for h in hands if h.get("chip_delta", 0) < 0)
        pushes = total - wins - losses
        net_chips = sum(h.get("chip_delta", 0) for h in hands)
        avg_bb = max(1, sum(h.get("big_blind", 2) for h in hands) / max(total, 1))
        bb_per_100 = (net_chips / avg_bb) / max(total, 1) * 100

        vpip_hands = 0
        for h in hands:
            if h.get("street_reached", "Preflop") != "Preflop":
                vpip_hands += 1
            elif h.get("chip_delta", 0) != 0:
                vpip_hands += 1
        vpip = vpip_hands / max(total, 1)

        return {
            "hands": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": round(wins / max(total, 1), 4),
            "net_chips": net_chips,
            "bb_per_100": round(bb_per_100, 2),
            "vpip": round(vpip, 4),
            "avg_chip_delta": round(net_chips / max(total, 1), 1),
        }

    def compute_advanced_stats(self, n: int = 1000) -> dict:
        """Compute VPIP, PFR, 3BET, FCB, WTSD, W$SD, AF from action records."""
        self._require_db()
        hands = self.db.get_recent_hands(n)
        if not hands:
            return {"hands": 0, "message": "no data"}

        total = len(hands)
        hand_ids = [h["hand_id"] for h in hands]

        # Collect actions for these hands
        conn = self.db._get_conn()
        action_counts: dict[str, int] = {}
        preflop_actions: dict[str, int] = {}
        postflop_actions: dict[str, int] = {}
        street_counts: dict[str, int] = {}

        for hid in hand_ids:
            rows = conn.execute(
                "SELECT street, action FROM actions WHERE hand_id=?", (hid,)
            ).fetchall()
            for r in rows:
                a = r["action"]
                s = r["street"]
                action_counts[a] = action_counts.get(a, 0) + 1
                street_counts[s] = street_counts.get(s, 0) + 1
                if s == "Preflop":
                    preflop_actions[a] = preflop_actions.get(a, 0) + 1
                else:
                    postflop_actions[a] = postflop_actions.get(a, 0) + 1

        total_actions = max(sum(action_counts.values()), 1)
        pf_total = max(sum(preflop_actions.values()), 1)

        # PFR: raise or bet preflop
        pfr = (preflop_actions.get("raise", 0) + preflop_actions.get("bet", 0)) / pf_total

        # 3BET: re-raise preflop (approximation from facing raise then raising)
        three_bet = preflop_actions.get("raise", 0) / pf_total

        # Aggression Factor: (bets + raises) / calls
        agg = (action_counts.get("bet", 0) + action_counts.get("raise", 0))
        passive = max(action_counts.get("call", 0) + action_counts.get("check", 0), 1)
        af = agg / passive

        # Fold percentages
        fold_total = max(action_counts.get("fold", 0), 0) / max(total_actions, 1)
        fcb = action_counts.get("fold", 0) / max(
            action_counts.get("fold", 0) + action_counts.get("call", 0)
            + action_counts.get("raise", 0), 1
        )

        # Showdown estimation
        river_hands = sum(1 for h in hands if h.get("street_reached") == "River")
        wtsd = river_hands / max(total, 1)
        wsd = sum(1 for h in hands
                  if h.get("street_reached") == "River" and h.get("chip_delta", 0) > 0)
        wsd_pct = wsd / max(river_hands, 1)

        return {
            "hands": total,
            "total_actions": total_actions,
            "vpip": self.compute_basic_stats(n).get("vpip", 0),
            "pfr": round(pfr, 4),
            "three_bet_pct": round(three_bet, 4),
            "fold_pct": round(fold_total, 4),
            "fold_to_cbet_estimate": round(fcb, 4),
            "wtsd": round(wtsd, 4),
            "wsd": round(wsd_pct, 4),
            "aggression_factor": round(af, 2),
            "action_distribution": {
                k: round(v / max(total_actions, 1), 4)
                for k, v in sorted(action_counts.items(), key=lambda x: -x[1])[:10]
            },
            "street_distribution": street_counts,
        }

    def compute_roi(self, n: int = 1000) -> float:
        """ROI = net_chips / total_invested."""
        self._require_db()
        hands = self.db.get_recent_hands(n)
        if not hands:
            return 0.0
        net = sum(h.get("chip_delta", 0) for h in hands)
        invested = sum(h.get("stack_start", 0) - h.get("stack_end", 0)
                       for h in hands if h.get("stack_start", 0) > h.get("stack_end", 0))
        if invested <= 0:
            return 0.0
        return round(net / max(invested, 1), 4)

    def generate_report(self, window_sizes: list[int] = None) -> str:
        """Generate a full analytics report for multiple window sizes."""
        if window_sizes is None:
            window_sizes = [100, 1000, 10000]

        self._require_db()
        total_hands = self.db.get_hand_count()
        lines = [
            "=" * 60,
            "POKER ANALYTICS REPORT",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            f"Total hands in database: {total_hands}",
            "=" * 60,
            "",
        ]

        for n in window_sizes:
            if total_hands < n // 10:
                lines.append(f"\n## Last {n} hands: INSUFFICIENT DATA ({total_hands} available)")
                continue

            basic = self.compute_basic_stats(min(n, total_hands))
            advanced = self.compute_advanced_stats(min(n, total_hands))
            roi = self.compute_roi(min(n, total_hands))

            lines += [
                f"\n## Last {min(n, total_hands)} Hands",
                "-" * 40,
                f"BB/100:        {basic.get('bb_per_100', 0):>8.2f}",
                f"ROI:           {roi:>8.2%}",
                f"Win Rate:      {basic.get('win_rate', 0):>8.1%}",
                f"Net Chips:     {basic.get('net_chips', 0):>8}",
                f"VPIP:          {advanced.get('vpip', 0):>8.1%}",
                f"PFR:           {advanced.get('pfr', 0):>8.1%}",
                f"3BET:          {advanced.get('three_bet_pct', 0):>8.1%}",
                f"Fold to CBet:  {advanced.get('fold_to_cbet_estimate', 0):>8.1%}",
                f"WTSD:          {advanced.get('wtsd', 0):>8.1%}",
                f"W$SD:          {advanced.get('wsd', 0):>8.1%}",
                f"Agg Factor:    {advanced.get('aggression_factor', 0):>8.1f}",
            ]

        # Position breakdown
        lines += ["", "## Position Breakdown", "-" * 40]
        pos_stats = self.db.get_position_stats(min(total_hands, 1000))
        for pos in ["BTN", "CO", "MP", "UTG", "SB", "BB"]:
            if pos in pos_stats:
                ps = pos_stats[pos]
                lines.append(
                    f"{pos:>4}: {ps['hands']:>5} hands | "
                    f"BB/100: {ps.get('bb_per_100', 0):>7.1f} | "
                    f"Win: {ps.get('win_rate', 0):>5.1%}"
                )

        # Street breakdown
        lines += ["", "## Action by Street", "-" * 40]
        street_data = self.db.get_street_stats(min(total_hands, 1000))
        for street, actions in sorted(street_data.items()):
            total_st = sum(actions.values()) or 1
            summary = ", ".join(
                f"{a}:{c}" for a, c in sorted(actions.items(), key=lambda x: -x[1])[:5]
            )
            lines.append(f"  {street} ({total_st}): {summary}")

        report = "\n".join(lines)
        return report

    def save_report(self, window_sizes: list[int] = None) -> str:
        """Generate and save report to reports/analytics-report.txt."""
        report = self.generate_report(window_sizes)
        path = self.output_dir / "analytics-report.txt"
        path.write_text(report)
        return str(path)

    def export_json(self, n: int = 1000) -> dict:
        """Export comprehensive stats as JSON."""
        self._require_db()
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_hands": self.db.get_hand_count(),
            "last_100": self.compute_basic_stats(100),
            "last_1000": self.compute_basic_stats(1000),
            "advanced_1000": self.compute_advanced_stats(1000),
            "roi_1000": self.compute_roi(1000),
            "by_position": self.db.get_position_stats(1000),
            "by_street": self.db.get_street_stats(1000),
        }

    def save_json(self, n: int = 1000) -> str:
        """Export stats as JSON to reports/analytics.json."""
        data = self.export_json(n)
        path = self.output_dir / "analytics.json"
        path.write_text(json.dumps(data, indent=2))
        return str(path)
