"""Leak Detector — automatic weakness identification from hand history.

Detects:
  - Over-calling (calling too much, getting to showdown with weak hands)
  - Over-folding (folding in spots with good pot odds)
  - Over-bluffing (bluffing with low success rate)
  - Position errors (losing from EP, not stealing enough from LP)
  - River losses (leaking money on the river)
  - Turn losses
  - Postflop losses

Outputs: leak_report.json
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class LeakDetector:
    """Analyze hand history to find systematic weaknesses."""

    # Thresholds for leak detection
    HIGH_FOLD_THRESHOLD = 0.45       # >45% fold = over-folding
    HIGH_CALL_THRESHOLD = 0.35       # >35% call = over-calling
    LOW_AGGRESSION_THRESHOLD = 1.0   # AF < 1.0 = too passive
    HIGH_BLUFF_THRESHOLD = 0.35      # >35% river bet with weak hand = over-bluffing
    RIVER_LOSS_THRESHOLD = -1.0      # BB/100 on river below this = leak
    POSITION_LOSS_THRESHOLD = -2.0   # BB/100 from position below this = leak

    def __init__(self, db=None, output_dir: str = "reports"):
        self.db = db
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def set_db(self, db):
        self.db = db

    def _require_db(self):
        if self.db is None:
            raise RuntimeError("LeakDetector: no database set.")

    def detect_all(self, n: int = 2000) -> dict:
        """Run all leak detection checks and return findings."""
        self._require_db()
        leaks = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hands_analyzed": 0,
            "leaks_found": [],
            "severity": "none",
            "details": {},
        }

        # Gather data
        hands = self.db.get_recent_hands(n)
        if not hands:
            leaks["message"] = "insufficient data"
            return leaks

        leaks["hands_analyzed"] = len(hands)

        # Run individual detectors
        folding_leak = self._detect_over_folding(hands)
        calling_leak = self._detect_over_calling(hands)
        bluffing_leak = self._detect_over_bluffing(hands)
        position_leaks = self._detect_position_errors(hands)
        river_leak = self._detect_river_losses(hands)
        turn_leak = self._detect_turn_losses(hands)
        postflop_leak = self._detect_postflop_losses(hands)

        for leak in [folding_leak, calling_leak, bluffing_leak, river_leak, turn_leak, postflop_leak]:
            if leak:
                leaks["leaks_found"].append(leak)
        if position_leaks:
            leaks["leaks_found"].extend(position_leaks)

        # Determine severity
        severities = [l.get("severity", "low") for l in leaks["leaks_found"]]
        if "critical" in severities:
            leaks["severity"] = "critical"
        elif severities.count("high") >= 2 or severities.count("medium") >= 3:
            leaks["severity"] = "high"
        elif any(s in ("high", "medium") for s in severities):
            leaks["severity"] = "medium"
        elif severities:
            leaks["severity"] = "low"

        # Summary
        leaks["summary"] = self._generate_summary(leaks)
        leaks["details"] = {
            "folding": folding_leak,
            "calling": calling_leak,
            "bluffing": bluffing_leak,
            "position_errors": position_leaks,
            "river_losses": river_leak,
            "turn_losses": turn_leak,
            "postflop_losses": postflop_leak,
        }

        return leaks

    def _detect_over_folding(self, hands: list[dict]) -> dict | None:
        """Detect when we're folding more than is optimal."""
        conn = self.db._get_conn()
        total_folds = 0
        total_actions = 0
        folds_vs_bet = 0
        faces_bet = 0

        for h in hands:
            actions = conn.execute(
                "SELECT action FROM actions WHERE hand_id=?",
                (h["hand_id"],)
            ).fetchall()
            for i, a in enumerate(actions):
                total_actions += 1
                if a["action"] == "fold":
                    total_folds += 1
                    # Check if folding vs a bet/raise
                    if i > 0 and actions[i - 1]["action"] in ("bet", "raise"):
                        folds_vs_bet += 1
                        faces_bet += 1
                elif a["action"] in ("bet", "raise"):
                    pass

        fold_pct = total_folds / max(total_actions, 1)
        if fold_pct > self.HIGH_FOLD_THRESHOLD:
            severity = "critical" if fold_pct > 0.55 else ("high" if fold_pct > 0.50 else "medium")
            return {
                "type": "over_folding",
                "severity": severity,
                "fold_pct": round(fold_pct, 3),
                "total_folds": total_folds,
                "total_actions": total_actions,
                "suggestion": "Call more in marginal spots. Look for good pot odds situations.",
                "adjustment": {"FOLD_TO_CBET_FACTOR": max(0.5, 1.0 - (fold_pct - 0.40) * 2)},
            }
        return None

    def _detect_over_calling(self, hands: list[dict]) -> dict | None:
        """Detect calling station behavior — calling too much without winning."""
        conn = self.db._get_conn()
        total_calls = 0
        total_actions = 0
        calls_lost = 0
        calls_with_loss_data = 0

        for h in hands:
            actions = conn.execute(
                "SELECT action FROM actions WHERE hand_id=?",
                (h["hand_id"],)
            ).fetchall()
            for a in actions:
                total_actions += 1
                if a["action"] == "call":
                    total_calls += 1
                    if h.get("chip_delta", 0) < 0:
                        calls_lost += 1
                    calls_with_loss_data += 1

        call_pct = total_calls / max(total_actions, 1)
        call_loss_pct = calls_lost / max(calls_with_loss_data, 1)

        if call_pct > self.HIGH_CALL_THRESHOLD and call_loss_pct > 0.55:
            severity = "high" if call_pct > 0.40 else "medium"
            return {
                "type": "over_calling",
                "severity": severity,
                "call_pct": round(call_pct, 3),
                "call_loss_pct": round(call_loss_pct, 3),
                "total_calls": total_calls,
                "suggestion": "Fold more to aggression. Stop calling down light.",
                "adjustment": {"CALL_DOWN_FACTOR": max(0.5, 1.0 - (call_pct - 0.30) * 3)},
            }
        return None

    def _detect_over_bluffing(self, hands: list[dict]) -> dict | None:
        """Detect bluffing too much — river bets that lose."""
        conn = self.db._get_conn()
        river_bets = 0
        river_bets_lost = 0

        for h in hands:
            if h.get("street_reached") != "River":
                continue
            actions = conn.execute(
                "SELECT action FROM actions WHERE hand_id=? AND street='River'",
                (h["hand_id"],)
            ).fetchall()
            for a in actions:
                if a["action"] in ("bet", "raise"):
                    river_bets += 1
                    if h.get("chip_delta", 0) < 0:
                        river_bets_lost += 1

        if river_bets >= 10:
            bluff_loss_pct = river_bets_lost / max(river_bets, 1)
            if bluff_loss_pct > 0.55:
                return {
                    "type": "over_bluffing",
                    "severity": "high" if bluff_loss_pct > 0.65 else "medium",
                    "river_bet_count": river_bets,
                    "river_bet_loss_pct": round(bluff_loss_pct, 3),
                    "suggestion": "Reduce river bluffs. Pick better bluff candidates with blockers.",
                    "adjustment": {"BLUFF_FACTOR": max(0.3, 1.0 - (bluff_loss_pct - 0.50) * 2)},
                }
        return None

    def _detect_position_errors(self, hands: list[dict]) -> list[dict]:
        """Find positions where we're consistently losing money."""
        position_stats = self.db.get_position_stats(len(hands))
        errors = []

        pos_order = ["UTG", "MP", "CO", "BTN", "SB", "BB"]
        for pos in pos_order:
            if pos not in position_stats:
                continue
            ps = position_stats[pos]
            bb100 = ps.get("bb_per_100", 0)
            if bb100 < self.POSITION_LOSS_THRESHOLD:
                severity = "critical" if bb100 < -10 else ("high" if bb100 < -5 else "medium")
                suggestion = ""
                if pos in ("UTG", "MP"):
                    suggestion = f"Tighten opening range from {pos}. Only play premium hands."
                elif pos in ("SB", "BB"):
                    suggestion = f"Defend blinds more selectively from {pos}. Don't call 3bets OOP light."
                else:
                    suggestion = f"Review {pos} play. Should be profitable position."

                errors.append({
                    "type": "position_loss",
                    "position": pos,
                    "severity": severity,
                    "bb_per_100": round(bb100, 2),
                    "hands": ps.get("hands", 0),
                    "suggestion": suggestion,
                })
        return errors

    def _detect_river_losses(self, hands: list[dict]) -> dict | None:
        """Detect systematic river losses."""
        river_hands = [h for h in hands if h.get("street_reached") == "River"]
        if len(river_hands) < 10:
            return None

        river_net = sum(h.get("chip_delta", 0) for h in river_hands)
        avg_bb = max(1, sum(h.get("big_blind", 2) for h in river_hands) / max(len(river_hands), 1))
        river_bb100 = (river_net / avg_bb) / max(len(river_hands), 1) * 100

        if river_bb100 < self.RIVER_LOSS_THRESHOLD:
            lost_river = sum(h.get("chip_delta", 0) for h in river_hands if h.get("chip_delta", 0) < 0)
            severity = "critical" if river_bb100 < -5 else ("high" if river_bb100 < -2 else "medium")
            return {
                "type": "river_losses",
                "severity": severity,
                "river_hands": len(river_hands),
                "river_bb_per_100": round(river_bb100, 2),
                "river_net": river_net,
                "total_lost": lost_river,
                "suggestion": "Stop calling river bets with medium-strength hands. Value bet thinner.",
                "adjustment": {
                    "BLUFF_CATCH_FACTOR": max(0.3, 1.0 - abs(river_bb100) * 0.05),
                    "VALUE_BET_THIN": min(1.5, 1.0 + abs(river_bb100) * 0.05),
                },
            }
        return None

    def _detect_turn_losses(self, hands: list[dict]) -> dict | None:
        """Detect systematic turn losses."""
        turn_hands = [
            h for h in hands
            if h.get("street_reached") in ("Turn", "River")
        ]
        if len(turn_hands) < 10:
            return None

        # Find hands where we lost money and saw the turn
        turn_lost = [h for h in turn_hands if h.get("chip_delta", 0) < -5]
        if len(turn_lost) >= len(turn_hands) * 0.30:
            turn_net = sum(h.get("chip_delta", 0) for h in turn_hands)
            avg_bb = max(1, sum(h.get("big_blind", 2) for h in turn_hands) / max(len(turn_hands), 1))
            turn_bb100 = (turn_net / avg_bb) / max(len(turn_hands), 1) * 100

            if turn_bb100 < -1:
                return {
                    "type": "turn_losses",
                    "severity": "medium",
                    "turn_hands": len(turn_hands),
                    "turn_bb_per_100": round(turn_bb100, 2),
                    "turn_net": turn_net,
                    "suggestion": "Evaluate turn barrel frequency. Consider pot control with marginal hands.",
                    "adjustment": {"DOUBLE_BARREL_FACTOR": 0.8},
                }
        return None

    def _detect_postflop_losses(self, hands: list[dict]) -> dict | None:
        """Detect systematic postflop losses."""
        postflop = [h for h in hands if h.get("street_reached") != "Preflop"]
        if len(postflop) < 10:
            return None

        postflop_net = sum(h.get("chip_delta", 0) for h in postflop)
        avg_bb = max(1, sum(h.get("big_blind", 2) for h in postflop) / max(len(postflop), 1))
        pf_bb100 = (postflop_net / avg_bb) / max(len(postflop), 1) * 100

        if pf_bb100 < -3:
            severity = "critical" if pf_bb100 < -8 else ("high" if pf_bb100 < -5 else "medium")
            return {
                "type": "postflop_losses",
                "severity": severity,
                "postflop_hands": len(postflop),
                "postflop_bb_per_100": round(pf_bb100, 2),
                "postflop_net": postflop_net,
                "suggestion": "Reduce postflop aggression without strong hands. Cbet less on bad boards.",
                "adjustment": {
                    "CBET_FACTOR": 0.8,
                    "DOUBLE_BARREL_FACTOR": 0.7,
                },
            }
        return None

    def _generate_summary(self, results: dict) -> str:
        """Generate a concise summary of findings."""
        if not results["leaks_found"]:
            return "No significant leaks detected. Strategy is performing well."

        top_leaks = sorted(results["leaks_found"],
                          key=lambda l: {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(l.get("severity", "low"), 0),
                          reverse=True)[:3]

        lines = [f"Found {len(results['leaks_found'])} leak(s) (severity: {results['severity']})."]
        for l in top_leaks:
            lines.append(f"  [{l.get('severity', '?').upper()}] {l['type']}: {l.get('suggestion', '')}")
        return " ".join(lines)

    def save_report(self) -> str:
        """Detect leaks and save to leak_report.json."""
        results = self.detect_all()
        path = self.output_dir / "leak_report.json"
        path.write_text(json.dumps(results, indent=2))
        return str(path)
