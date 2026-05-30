"""Arena Population Analyzer — learn from real opponents.

Observes opponent actions from Arena recentEvents, builds statistical profiles,
classifies archetypes, detects leaks, and tracks population trends over time.

Usage:
    from src.observability.population_analyzer import PopulationAnalyzer

    analyzer = PopulationAnalyzer()
    analyzer.ingest_table_events(table)  # call on every pending-actions poll
    analyzer.generate_report()           # after session or daily
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
POPULATION_DIR = PROJECT_ROOT / "arena_population"
PROFILES_FILE = POPULATION_DIR / "profiles.json"
HISTORY_FILE = POPULATION_DIR / "history.jsonl"
REPORT_FILE = POPULATION_DIR / "arena_population_report.md"

# ─── Classification thresholds ────────────────────────────────────────

ARCHETYPE_RULES: list[dict] = [
    {"name": "Nit", "vpip_max": 0.18, "pfr_max": 0.12, "af_max": 2.5, "min_hands": 8},
    {"name": "TAG", "vpip_min": 0.14, "vpip_max": 0.28, "pfr_min": 0.10, "pfr_max": 0.24, "af_min": 1.8, "min_hands": 10},
    {"name": "LAG", "vpip_min": 0.22, "vpip_max": 0.42, "pfr_min": 0.16, "pfr_max": 0.38, "af_min": 2.5, "min_hands": 10},
    {"name": "Calling Station", "vpip_min": 0.28, "pfr_max": 0.15, "af_max": 1.6, "min_hands": 8},
    {"name": "Maniac", "vpip_min": 0.38, "pfr_min": 0.25, "af_min": 3.0, "min_hands": 8},
]


def classify_opponent(stats: dict) -> str:
    """Classify opponent into archetype based on observed stats."""
    hands = stats.get("total_hands", 0)
    vpip = stats.get("vpip", 0)
    pfr = stats.get("pfr", 0)
    af = stats.get("aggression_factor", 1.0)

    if hands < 5:
        return "Unknown"

    for rule in ARCHETYPE_RULES:
        if hands < rule.get("min_hands", 5):
            continue
        if "vpip_max" in rule and vpip > rule["vpip_max"]:
            continue
        if "vpip_min" in rule and vpip < rule["vpip_min"]:
            continue
        if "pfr_max" in rule and pfr > rule["pfr_max"]:
            continue
        if "pfr_min" in rule and pfr < rule["pfr_min"]:
            continue
        if "af_max" in rule and af > rule["af_max"]:
            continue
        if "af_min" in rule and af < rule["af_min"]:
            continue
        return rule["name"]

    # Fallback classification
    if vpip < 0.20 and pfr < 0.12:
        return "Nit"
    if vpip > 0.35 and pfr > 0.22:
        return "Maniac"
    if vpip > 0.30 and pfr < 0.15:
        return "Calling Station"
    if pfr / max(vpip, 0.01) > 0.7:
        return "LAG"
    if pfr / max(vpip, 0.01) > 0.4:
        return "TAG"
    return "Unknown"


# ─── Leak definitions ─────────────────────────────────────────────────

LEAK_THRESHOLDS = {
    "overfolding": {"fold_to_cbet_pct": (0.70, 1.0), "min_opps": 5,
                    "description": "Folds to cbet > 70% — exploitable with high cbet frequency"},
    "overcalling": {"vpip": (0.40, 1.0), "pfr": (0, 0.12), "min_hands": 10,
                   "description": "VPIP > 40% with PFR < 12% — calls too wide, value bet relentlessly"},
    "overbluffing": {"aggression_factor": (4.0, 20.0), "pfr": (0.20, 1.0), "min_hands": 10,
                    "description": "AF > 4.0 with high PFR — likely over-bluffing, trap more"},
    "sizing_tells": {"min_hands": 10,
                    "description": "Detected via inconsistent bet sizing pattern (requires size data)"},
    "river_mistakes": {"min_hands": 15,
                      "description": "River fold > 55% or river call > 70% — exploitable on river"},
}

ACTION_AGGRESSIVE = {"bet", "raise", "all-in", "all_in", "allin", "Bet", "Raise", "AllIn"}
ACTION_PASSIVE = {"call", "check", "fold", "Call", "Check", "Fold"}
ACTION_VPIP = {"call", "raise", "bet", "all-in", "all_in", "allin", "Call", "Raise", "Bet", "AllIn"}


class PopulationAnalyzer:
    """Tracks opponent population from Arena event streams."""

    def __init__(self):
        self.opponents: dict[str, dict] = {}
        self._seen_event_ids: set[str] = set()
        self._seen_table_ids: set[str] = set()
        self._hand_counter: dict[str, int] = {}
        self._load_profiles()

    # ─── Data ingestion ───────────────────────────────────────────────

    def ingest_table_events(self, table: dict, our_agent_id: str = "") -> int:
        """Parse recentEvents from an Arena table and update opponent profiles.

        Returns number of new actions ingested.
        """
        events = table.get("recentEvents") or []
        if not events:
            return 0

        # Track hand: one hand per unique tableId
        table_id = table.get("tableId", "")
        is_new_hand = False
        if table_id and table_id not in self._seen_table_ids:
            self._seen_table_ids.add(table_id)
            is_new_hand = True
            # Cleanup old table IDs (keep last 200)
            if len(self._seen_table_ids) > 500:
                self._seen_table_ids = set(list(self._seen_table_ids)[-200:])

        seats = table.get("seats") or []
        seat_to_agent: dict[int, str] = {}
        seat_to_name: dict[int, str] = {}
        for s in seats:
            sn = s.get("seatNumber")
            aid = s.get("agentId", "")
            if sn is not None and aid and aid != our_agent_id:
                seat_to_agent[sn] = aid
                seat_to_name[sn] = s.get("agentName") or s.get("agentHandle", "")

        street = table.get("street", "")
        ingested = 0

        for event in events:
            if event.get("type") != "ActionTaken":
                continue

            # Deduplicate: skip events we've already seen
            event_id = event.get("id", "")
            if event_id and event_id in self._seen_event_ids:
                continue
            if event_id:
                self._seen_event_ids.add(event_id)
            # Cleanup old event IDs (keep last 2000)
            if len(self._seen_event_ids) > 5000:
                self._seen_event_ids = set(list(self._seen_event_ids)[-2000:])

            summary = event.get("summary") or {}
            seat_num = summary.get("seatNumber")
            action = summary.get("action")
            amount = summary.get("amount")
            evt_street = event.get("street") or street

            if seat_num is None or not action:
                continue
            if seat_num not in seat_to_agent:
                continue

            agent_id = seat_to_agent[seat_num]
            agent_name = seat_to_name.get(seat_num, "")
            profile = self._get_or_create(agent_id, agent_name)

            # Count hand
            if is_new_hand:
                profile["total_hands"] = profile.get("total_hands", 0) + 1

            action_lower = action.lower() if isinstance(action, str) else ""

            # VPIP: voluntarily put money in pot (call/raise/bet preflop)
            if evt_street == "Preflop":
                # VPIP opportunity: any preflop action (excluding blinds posting)
                profile["vpip_opportunities"] += 1
                if action_lower in ACTION_VPIP:
                    profile["vpip_actions"] += 1

                # PFR: preflop raise
                profile["pfr_opportunities"] += 1
                if action_lower in {"raise", "bet", "all-in", "all_in", "allin"}:
                    profile["pfr_actions"] += 1

            # Aggression: bet/raise is aggressive, call/check/fold is passive
            if action_lower in ACTION_AGGRESSIVE:
                profile["aggressive_actions"] += 1
            elif action_lower in ACTION_PASSIVE:
                profile["passive_actions"] += 1

            # Fold to cbet: fold on flop when facing bet
            if evt_street == "Flop" and action_lower == "fold":
                profile["fold_to_cbet_opps"] += 1
                profile["fold_to_cbet_actions"] += 1
            elif evt_street == "Flop" and action_lower in {"call", "raise"}:
                profile["fold_to_cbet_opps"] += 1

            # River actions
            if evt_street == "River":
                profile["river_actions"] = profile.get("river_actions", 0) + 1
                if action_lower == "fold":
                    profile["river_folds"] = profile.get("river_folds", 0) + 1
                elif action_lower in {"call", "check"}:
                    profile["river_calls"] = profile.get("river_calls", 0) + 1

            # Track last seen
            profile["last_seen_at"] = time.time()
            profile["last_action"] = action_lower
            ingested += 1

        return ingested

    def _get_or_create(self, agent_id: str, agent_name: str = "") -> dict:
        """Get or create an opponent profile dict."""
        if agent_id not in self.opponents:
            self.opponents[agent_id] = {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "first_seen_at": time.time(),
                "total_hands": 0,
                "vpip_opportunities": 0,
                "vpip_actions": 0,
                "pfr_opportunities": 0,
                "pfr_actions": 0,
                "three_bet_opps": 0,
                "three_bet_actions": 0,
                "fold_to_cbet_opps": 0,
                "fold_to_cbet_actions": 0,
                "aggressive_actions": 0,
                "passive_actions": 0,
                "showdowns": 0,
                "river_actions": 0,
                "river_folds": 0,
                "river_calls": 0,
                "last_seen_at": 0,
                "last_action": "",
            }
        elif agent_name and not self.opponents[agent_id].get("agent_name"):
            self.opponents[agent_id]["agent_name"] = agent_name
        return self.opponents[agent_id]

    # ─── Computed properties ──────────────────────────────────────────

    def get_vpip(self, profile: dict) -> float:
        opps = profile.get("vpip_opportunities", 0)
        if opps == 0:
            return 0.0
        return profile["vpip_actions"] / opps

    def get_pfr(self, profile: dict) -> float:
        opps = profile.get("pfr_opportunities", 0)
        if opps == 0:
            return 0.0
        return profile["pfr_actions"] / opps

    def get_af(self, profile: dict) -> float:
        passive = profile.get("passive_actions", 0)
        if passive == 0:
            return 10.0 if profile.get("aggressive_actions", 0) > 0 else 1.0
        return profile["aggressive_actions"] / passive

    def get_fold_to_cbet(self, profile: dict) -> float:
        opps = profile.get("fold_to_cbet_opps", 0)
        if opps == 0:
            return 0.0
        return profile["fold_to_cbet_actions"] / opps

    def get_river_fold_pct(self, profile: dict) -> float:
        actions = profile.get("river_actions", 0)
        if actions == 0:
            return 0.0
        return profile.get("river_folds", 0) / actions

    # ─── Population statistics ────────────────────────────────────────

    def get_population_stats(self) -> dict:
        """Compute aggregate population statistics."""
        profiles = list(self.opponents.values())
        active = [p for p in profiles if p.get("vpip_opportunities", 0) >= 2]

        if not active:
            return {"total_opponents": len(profiles), "classified": 0, "message": "Insufficient data"}

        vpips = [self.get_vpip(p) for p in active]
        pfrs = [self.get_pfr(p) for p in active]
        afs = [self.get_af(p) for p in active]

        archetypes: dict[str, int] = defaultdict(int)
        for p in active:
            enriched = dict(p)
            enriched["vpip"] = self.get_vpip(p)
            enriched["pfr"] = self.get_pfr(p)
            enriched["aggression_factor"] = self.get_af(p)
            enriched["fold_to_cbet_pct"] = self.get_fold_to_cbet(p)
            enriched["archetype"] = classify_opponent(enriched)
            archetypes[enriched["archetype"]] += 1

        return {
            "total_opponents": len(profiles),
            "active_opponents": len(active),
            "avg_vpip": sum(vpips) / len(vpips) if vpips else 0,
            "avg_pfr": sum(pfrs) / len(pfrs) if pfrs else 0,
            "avg_af": sum(afs) / len(afs) if afs else 0,
            "median_vpip": sorted(vpips)[len(vpips) // 2] if vpips else 0,
            "median_pfr": sorted(pfrs)[len(pfrs) // 2] if pfrs else 0,
            "archetype_distribution": dict(archetypes),
            "most_common_archetype": max(archetypes, key=archetypes.get) if archetypes else "Unknown",
        }

    def get_opponent_leaks(self) -> list[dict]:
        """Identify leaks for each opponent with sufficient data."""
        leaks = []
        for aid, p in self.opponents.items():
            hands = p.get("total_hands", 0)
            if hands < 5:
                continue

            vpip = self.get_vpip(p)
            pfr = self.get_pfr(p)
            af = self.get_af(p)
            ftc = self.get_fold_to_cbet(p)
            river_fold = self.get_river_fold_pct(p)
            ftc_opps = p.get("fold_to_cbet_opps", 0)

            opponent_leaks = []

            # Overfolding detection
            if ftc_opps >= 5 and ftc > 0.70:
                opponent_leaks.append({
                    "type": "overfolding",
                    "severity": "high" if ftc > 0.80 else "medium",
                    "evidence": f"Fold to cbet: {ftc:.0%} ({p['fold_to_cbet_actions']}/{ftc_opps})",
                    "exploit": "Cbet 80-100% of flops against this opponent",
                })

            # Overcalling detection
            if hands >= 10 and vpip > 0.40 and pfr < 0.12:
                opponent_leaks.append({
                    "type": "overcalling",
                    "severity": "high" if vpip > 0.50 else "medium",
                    "evidence": f"VPIP: {vpip:.0%}, PFR: {pfr:.0%}",
                    "exploit": "Value bet thinner, reduce bluffs, increase sizing",
                })

            # Overbluffing detection
            if hands >= 10 and af > 4.0 and pfr > 0.20:
                opponent_leaks.append({
                    "type": "overbluffing",
                    "severity": "high" if af > 6.0 else "medium",
                    "evidence": f"AF: {af:.1f}, PFR: {pfr:.0%}",
                    "exploit": "Trap more, call down lighter, induce bluffs",
                })

            # River mistakes
            if p.get("river_actions", 0) >= 5:
                if river_fold > 0.55:
                    opponent_leaks.append({
                        "type": "river_mistakes",
                        "severity": "medium",
                        "evidence": f"River fold: {river_fold:.0%}",
                        "exploit": "Bluff rivers more frequently against this opponent",
                    })
                elif hasattr(self, '_river_call_pct'):
                    rc = self._river_call_pct
                    if rc > 0.70:
                        opponent_leaks.append({
                            "type": "river_mistakes",
                            "severity": "medium",
                            "evidence": f"River call: {rc:.0%} (sticky on rivers)",
                            "exploit": "Value bet wider on rivers, eliminate river bluffs",
                        })

            if opponent_leaks:
                leaks.append({
                    "agent_id": aid,
                    "agent_name": p.get("agent_name", aid),
                    "hands": hands,
                    "archetype": classify_opponent({**p, "vpip": vpip, "pfr": pfr, "aggression_factor": af}),
                    "vpip": vpip,
                    "pfr": pfr,
                    "af": af,
                    "leaks": opponent_leaks,
                })

        return sorted(leaks, key=lambda x: -len(x["leaks"]))

    # ─── Persistence ──────────────────────────────────────────────────

    def save_profiles(self) -> None:
        """Persist opponent profiles to disk."""
        POPULATION_DIR.mkdir(parents=True, exist_ok=True)
        with open(PROFILES_FILE, "w") as f:
            json.dump(self.opponents, f, indent=2, ensure_ascii=False, default=str)

    def _load_profiles(self) -> None:
        """Load opponent profiles from disk."""
        if PROFILES_FILE.exists():
            try:
                with open(PROFILES_FILE) as f:
                    self.opponents = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.opponents = {}

    def append_history(self) -> dict:
        """Append a daily population snapshot to history.jsonl."""
        stats = self.get_population_stats()
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "total_opponents": stats.get("total_opponents", 0),
            "active_opponents": stats.get("active_opponents", 0),
            "avg_vpip": round(stats.get("avg_vpip", 0), 4),
            "avg_pfr": round(stats.get("avg_pfr", 0), 4),
            "avg_af": round(stats.get("avg_af", 0), 2),
            "archetype_distribution": stats.get("archetype_distribution", {}),
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        return record

    def load_history(self) -> list[dict]:
        """Load all daily history snapshots."""
        if not HISTORY_FILE.exists():
            return []
        records = []
        with open(HISTORY_FILE) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    # ─── Report generation ────────────────────────────────────────────

    def generate_report(self) -> Path:
        """Generate arena_population_report.md with full analysis."""
        self.save_profiles()
        self.append_history()

        stats = self.get_population_stats()
        leaks = self.get_opponent_leaks()
        history = self.load_history()

        lines = [
            "# Arena Population Report",
            "",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            f"**Opponents tracked:** {stats.get('total_opponents', 0)} ({stats.get('active_opponents', 0)} active)",
            "",
            "---",
            "",
            "## Population Statistics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Average VPIP | **{stats.get('avg_vpip', 0):.1%}** |",
            f"| Average PFR | **{stats.get('avg_pfr', 0):.1%}** |",
            f"| Average AF | **{stats.get('avg_af', 0):.2f}** |",
            f"| Median VPIP | {stats.get('median_vpip', 0):.1%} |",
            f"| Median PFR | {stats.get('median_pfr', 0):.1%} |",
            f"| Most common archetype | **{stats.get('most_common_archetype', 'Unknown')}** |",
            "",
            "## Archetype Distribution",
            "",
        ]

        archetypes = stats.get("archetype_distribution", {})
        total = sum(archetypes.values()) or 1
        for name in ["Nit", "TAG", "LAG", "Calling Station", "Maniac", "Unknown"]:
            count = archetypes.get(name, 0)
            bar = "█" * min(int(count / max(total, 1) * 40), 40)
            lines.append(f"- **{name}**: {count} ({count/total*100:.0f}%) {bar}")

        lines += [
            "",
            "## Exploit Opportunities",
            "",
        ]

        if stats.get("avg_vpip", 0) > 0.35:
            lines.append("- **Field is loose (high VPIP)** — tighten up, value bet thinner, reduce bluffs")
        if stats.get("avg_vpip", 0) < 0.20:
            lines.append("- **Field is tight (low VPIP)** — steal blinds more, widen preflop opens")
        if stats.get("avg_pfr", 0) > 0.20:
            lines.append("- **Field is aggressive preflop** — trap more with premiums, 4bet wider")
        if stats.get("avg_af", 0) > 3.0:
            lines.append("- **Field is aggressive postflop** — call down lighter, induce bluffs")
        if stats.get("avg_af", 0) < 1.5:
            lines.append("- **Field is passive postflop** — cbet more, fold to aggression")

        if archetypes.get("Nit", 0) > total * 0.3:
            lines.append("- **Nit-heavy field** — steal blinds relentlessly, cbet nearly always")
        if archetypes.get("Calling Station", 0) > total * 0.3:
            lines.append("- **Calling-station-heavy field** — value bet wider, eliminate bluffs")

        lines += [
            "",
            "## Opponent Leaks Detected",
            "",
        ]

        if not leaks:
            lines.append("*No significant leaks detected — need more hands.*")
        else:
            lines.append(f"**{len(leaks)} opponents** with exploitable leaks:")
            lines.append("")
            for i, l in enumerate(leaks[:15]):
                lines.append(f"### {i+1}. {l['agent_name']} ({l['archetype']})")
                lines.append(f"*{l['hands']} hands | VPIP: {l['vpip']:.0%} | PFR: {l['pfr']:.0%} | AF: {l['af']:.1f}*")
                lines.append("")
                for lk in l["leaks"]:
                    severity_icon = "**HIGH**" if lk["severity"] == "high" else "MEDIUM"
                    lines.append(f"- [{severity_icon}] **{lk['type']}**: {lk['evidence']}")
                    lines.append(f"  → *{lk['exploit']}*")
                lines.append("")

        # Detailed profiles table
        lines += [
            "",
            "## Individual Profiles",
            "",
            "| Opponent | Hands | VPIP | PFR | AF | Fold to CBet | Archetype |",
            "|----------|-------|------|-----|----|-------------|-----------|",
        ]

        profiles = sorted(
            self.opponents.values(),
            key=lambda p: p.get("total_hands", 0),
            reverse=True,
        )
        for p in profiles[:30]:
            hands = p.get("total_hands", 0)
            if hands < 1:
                continue
            vpip = self.get_vpip(p)
            pfr = self.get_pfr(p)
            af = self.get_af(p)
            ftc = self.get_fold_to_cbet(p)
            arch = classify_opponent({**p, "vpip": vpip, "pfr": pfr, "aggression_factor": af})
            name = (p.get("agent_name") or p["agent_id"])[:25]
            lines.append(
                f"| {name} | {hands} | {vpip:.0%} | {pfr:.0%} | {af:.1f} | {ftc:.0%} | {arch} |"
            )

        # Trend analysis
        if len(history) >= 2:
            lines += [
                "",
                "## Population Trends",
                "",
            ]
            prev = history[-2]
            curr = history[-1]
            lines.append(f"| Metric | Previous | Current | Trend |")
            lines.append(f"|--------|----------|---------|-------|")
            for key, label in [("avg_vpip", "VPIP"), ("avg_pfr", "PFR"), ("avg_af", "AF")]:
                pv = prev.get(key, 0)
                cv = curr.get(key, 0)
                delta = cv - pv
                arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "→")
                lines.append(f"| {label} | {pv:.1%} | {cv:.1%} | {arrow} {delta:+.2%} |")

        report = "\n".join(lines) + "\n"

        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(report)
        return REPORT_FILE


# ─── Convenience ──────────────────────────────────────────────────────

_global_analyzer: Optional[PopulationAnalyzer] = None


def get_analyzer() -> PopulationAnalyzer:
    global _global_analyzer
    if _global_analyzer is None:
        _global_analyzer = PopulationAnalyzer()
    return _global_analyzer
