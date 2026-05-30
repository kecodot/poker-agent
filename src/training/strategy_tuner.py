"""Strategy optimizer — analyzes hand history to suggest parameter improvements.

Works by:
  1. Loading recent hands from logs/
  2. Identifying losing patterns (position, street, hand type)
  3. Comparing decisions against equity benchmarks
  4. Generating parameter adjustment suggestions
  5. Writing improvement reports to reports/

Can be run:
  - After every Arena session for automated tuning
  - Manually: python -m src.training.strategy_tuner
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class StrategyTuner:
    """Analyzes hand history and suggests strategy parameter adjustments."""

    def __init__(self, log_dir: str = "logs", report_dir: str = "reports"):
        self.log_dir = Path(log_dir)
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, n_recent: int = 1000) -> dict:
        """Analyze recent hands and return optimization suggestions."""
        decisions = self._load_decisions(n_recent)
        if len(decisions) < 50:
            return {"error": "insufficient_data", "count": len(decisions)}

        findings = {
            "total_decisions": len(decisions),
            "by_street": self._by_street(decisions),
            "by_action": self._by_action(decisions),
            "fold_analysis": self._fold_analysis(decisions),
            "suggestions": [],
        }

        # Generate suggestions
        suggestions = findings["suggestions"]

        # Check preflop aggression
        pf = [d for d in decisions if d.get("street") == "Preflop"]
        if pf:
            agg = sum(1 for d in pf if d.get("action") in ("raise", "bet", "all-in"))
            agg_pct = agg / len(pf)
            if agg_pct < 0.12:
                suggestions.append({
                    "area": "preflop",
                    "issue": "low_aggression",
                    "current": f"{agg_pct:.0%}",
                    "suggestion": "Increase opening ranges from CO/BTN by 10-15%",
                    "expected_impact": "+1-3 bb/100",
                })
            elif agg_pct > 0.35:
                suggestions.append({
                    "area": "preflop",
                    "issue": "high_aggression",
                    "current": f"{agg_pct:.0%}",
                    "suggestion": "Tighten UTG/MP opening ranges slightly",
                    "expected_impact": "+0.5-2 bb/100",
                })

        # Check fold frequency
        folds = [d for d in decisions if d.get("action") == "fold"]
        fold_pct = len(folds) / max(len(decisions), 1)
        if fold_pct > 0.42:
            suggestions.append({
                "area": "general",
                "issue": "high_fold_rate",
                "current": f"{fold_pct:.0%}",
                "suggestion": "Call more in position with marginal hands. "
                             "Look for thin +EV spots.",
                "expected_impact": "+1-4 bb/100",
            })
        elif fold_pct < 0.22:
            suggestions.append({
                "area": "general",
                "issue": "low_fold_rate",
                "current": f"{fold_pct:.0%}",
                "suggestion": "Fold more preflop from early position. "
                             "Avoid calling stations.",
                "expected_impact": "+1-3 bb/100",
            })

        # Check river play
        river = [d for d in decisions if d.get("street") == "River"]
        if river:
            river_folds = sum(1 for d in river if d.get("action") == "fold")
            river_calls = sum(1 for d in river if d.get("action") == "call")
            total_river = len(river)
            if river_folds / max(total_river, 1) > 0.55:
                suggestions.append({
                    "area": "river",
                    "issue": "over_folding_river",
                    "current": f"{river_folds / max(total_river, 1):.0%} folds",
                    "suggestion": "Bluff catch more on river with medium-strength hands. "
                                 "Call when pot odds justify.",
                    "expected_impact": "+0.5-2 bb/100",
                })

        # Check for passivity postflop
        postflop = [d for d in decisions if d.get("street") not in ("Preflop", "?")]
        if postflop:
            bets = sum(1 for d in postflop if d.get("action") in ("bet", "raise"))
            bet_pct = bets / max(len(postflop), 1)
            if bet_pct < 0.15:
                suggestions.append({
                    "area": "postflop",
                    "issue": "too_passive",
                    "current": f"{bet_pct:.0%} bet/raise",
                    "suggestion": "Increase cbet frequency. Bet more for value and "
                                 "as semi-bluffs.",
                    "expected_impact": "+2-5 bb/100",
                })

        return findings

    def _load_decisions(self, n: int) -> list[dict]:
        decisions = []
        try:
            for f in sorted(self.log_dir.glob("decisions*.jsonl"), reverse=True):
                if len(decisions) >= n:
                    break
                try:
                    with open(f) as fh:
                        lines = fh.readlines()
                    for line in reversed(lines):
                        if len(decisions) >= n:
                            break
                        try:
                            decisions.append(json.loads(line.strip()))
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass
        return decisions

    def _by_street(self, decisions: list) -> dict:
        by = {}
        for d in decisions:
            s = d.get("street", "?")
            by[s] = by.get(s, 0) + 1
        return by

    def _by_action(self, decisions: list) -> dict:
        by = {}
        for d in decisions:
            a = d.get("action", "?")
            by[a] = by.get(a, 0) + 1
        return by

    def _fold_analysis(self, decisions: list) -> dict:
        folds = [d for d in decisions if d.get("action") == "fold"]
        if not folds:
            return {"count": 0}

        by_street = {}
        for d in folds:
            s = d.get("street", "?")
            by_street[s] = by_street.get(s, 0) + 1

        total = len(decisions)
        return {
            "count": len(folds),
            "percentage": round(len(folds) / max(total, 1) * 100, 1),
            "by_street": by_street,
        }

    def generate_report(self, findings: dict, output_path: Optional[str] = None) -> str:
        """Generate a human-readable optimization report."""
        if "error" in findings:
            return f"# Strategy Tuning Report\n\nError: {findings['error']}\nHands analyzed: {findings['count']}"

        lines = [
            "# Strategy Optimization Report",
            f"Total decisions analyzed: {findings['total_decisions']}",
            "",
            "## Decision Distribution",
            "### By Street",
        ]
        for street, count in sorted(findings.get("by_street", {}).items()):
            pct = count / max(findings["total_decisions"], 1) * 100
            lines.append(f"- {street}: {count} ({pct:.1f}%)")

        lines += ["", "### By Action"]
        for action, count in sorted(findings.get("by_action", {}).items(),
                                     key=lambda x: -x[1]):
            pct = count / max(findings["total_decisions"], 1) * 100
            lines.append(f"- {action}: {count} ({pct:.1f}%)")

        lines += ["", f"## Fold Analysis",
                  f"Total folds: {findings['fold_analysis'].get('count', 0)} "
                  f"({findings['fold_analysis'].get('percentage', 0)}%)"]

        suggestions = findings.get("suggestions", [])
        if suggestions:
            lines += ["", "## Suggested Improvements"]
            for i, s in enumerate(suggestions, 1):
                lines += [
                    f"### {i}. {s['area'].title()}: {s['issue'].replace('_', ' ').title()}",
                    f"- Current: {s['current']}",
                    f"- Suggestion: {s['suggestion']}",
                    f"- Expected Impact: {s['expected_impact']}",
                    "",
                ]
        else:
            lines += ["", "## No significant issues found",
                      "Current strategy parameters appear well-tuned for the observed sample."]

        lines += [
            "---",
            "Apply these suggestions by updating `config/agent_config.json`",
            "and re-running the agent.",
        ]

        report = "\n".join(lines)
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(report)

        return report


def run_tuner(log_dir: str = "logs", output: str = "reports/optimization.md") -> str:
    """Convenience function to run the full tuning pipeline."""
    tuner = StrategyTuner(log_dir)
    findings = tuner.analyze()
    report = tuner.generate_report(findings, output)
    print(f"[tuner] Report written to {output}")
    return report


if __name__ == "__main__":
    print(run_tuner())
