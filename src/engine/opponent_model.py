"""Opponent modeling — track VPIP/PFR/3BET/AF and generate player profiles.

Records all observed opponent actions and generates:
  - VPIP (Voluntarily Put money In Pot)
  - PFR (PreFlop Raise)
  - 3BET percentage
  - Fold to Cbet percentage
  - Aggression Factor
  - Player archetype classification (Nit, TAG, LAG, Maniac, Whale, Calling Station)

Data is persisted to JSON for cross-session continuity and synced to SQLite.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# ─── Data structures ───────────────────────────────────────────────

class OpponentStats:
    """Per-player statistics accumulated over observed hands."""

    def __init__(self, agent_id: str = "", handle: str = ""):
        self.agent_id = agent_id
        self.handle = handle
        self.total_hands = 0

        # Preflop
        self.vpip_opportunities = 0  # Times could voluntarily put money in
        self.vpip_actions = 0        # Times did put money in voluntarily
        self.pfr_opportunities = 0   # Times could raise preflop
        self.pfr_actions = 0         # Times did raise preflop
        self.three_bet_opps = 0      # Faces a raise
        self.three_bet_actions = 0   # Re-raises
        self.fold_to_3bet_opps = 0   # Raises then faces 3bet
        self.fold_to_3bet_actions = 0

        # Postflop
        self.cbet_opportunities = 0  # Times could cbet
        self.cbet_actions = 0        # Times did cbet
        self.fold_to_cbet_opps = 0   # Faces cbet
        self.fold_to_cbet_actions = 0

        # Aggression
        self.aggressive_actions = 0  # Bets + raises
        self.passive_actions = 0     # Calls + checks

        # Showdown
        self.showdowns = 0
        self.showdown_wins = 0

    @property
    def vpip(self) -> float:
        if self.vpip_opportunities == 0:
            return 0.0
        return self.vpip_actions / self.vpip_opportunities

    @property
    def pfr(self) -> float:
        if self.pfr_opportunities == 0:
            return 0.0
        return self.pfr_actions / self.pfr_opportunities

    @property
    def three_bet_pct(self) -> float:
        if self.three_bet_opps == 0:
            return 0.0
        return self.three_bet_actions / self.three_bet_opps

    @property
    def fold_to_3bet_pct(self) -> float:
        if self.fold_to_3bet_opps == 0:
            return 0.0
        return self.fold_to_3bet_actions / self.fold_to_3bet_opps

    @property
    def cbet_pct(self) -> float:
        if self.cbet_opportunities == 0:
            return 0.0
        return self.cbet_actions / self.cbet_opportunities

    @property
    def fold_to_cbet_pct(self) -> float:
        if self.fold_to_cbet_opps == 0:
            return 0.0
        return self.fold_to_cbet_actions / self.fold_to_cbet_opps

    @property
    def aggression_factor(self) -> float:
        if self.passive_actions == 0:
            return 10.0 if self.aggressive_actions > 0 else 1.0
        return self.aggressive_actions / self.passive_actions

    @property
    def archetype(self) -> str:
        """Classify player into archetype based on stats.

        Thresholds:
          Nit: VPIP < 15, PFR < 10
          TAG: VPIP 15-25, PFR 12-22, AF > 2
          LAG: VPIP 25-40, PFR 20-35, AF > 3
          Maniac: VPIP > 40, PFR > 30
          Whale: VPIP > 50, PFR < 15 (very loose-passive)
          Calling Station: VPIP > 30, PFR < 15, AF < 1.5 (calls too much)
          Unknown: insufficient data
          Passive Fish: VPIP > 25, PFR < 10
        """
        if self.total_hands < 10:
            return "Unknown"
        v = self.vpip
        p = self.pfr
        af = self.aggression_factor

        if v >= 0.50 and p < 0.15:
            return "Whale"
        if v > 0.30 and p < 0.15 and af < 1.5:
            return "Calling Station"
        if v < 0.15 and p < 0.10:
            return "Nit"
        if v < 0.25 and p < 0.22 and af >= 2.0:
            return "TAG"
        if v < 0.40 and p >= 0.20 and af >= 3.0:
            return "LAG"
        if v >= 0.40 and p > 0.30:
            return "Maniac"
        if v > 0.25 and p < 0.10:
            return "Passive Fish"
        if v < 0.20:
            return "Nit"
        return "Unknown"

    @property
    def fold_to_cbet_category(self) -> str:
        """How often does this player fold to cbets."""
        pct = self.fold_to_cbet_pct
        if self.fold_to_cbet_opps < 3:
            return "unknown"
        if pct > 0.65:
            return "high_fold"
        if pct > 0.40:
            return "normal"
        return "sticky"

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "handle": self.handle,
            "total_hands": self.total_hands,
            "vpip": self.vpip,
            "pfr": self.pfr,
            "three_bet_pct": self.three_bet_pct,
            "fold_to_3bet_pct": self.fold_to_3bet_pct,
            "cbet_pct": self.cbet_pct,
            "fold_to_cbet_pct": self.fold_to_cbet_pct,
            "aggression_factor": self.aggression_factor,
            "archetype": self.archetype,
            "fold_to_cbet_category": self.fold_to_cbet_category,
            "showdowns": self.showdowns,
            "showdown_wins": self.showdown_wins,
        }


class OpponentModel:
    """Manages opponent tracking across a session or multiple sessions."""

    def __init__(self, storage_path: str = "logs/opponents.json"):
        self.storage_path = storage_path
        self.players: dict[str, OpponentStats] = {}
        self._load()

    def _load(self) -> None:
        try:
            p = Path(self.storage_path)
            if p.exists():
                data = json.loads(p.read_text())
                for agent_id, d in data.items():
                    s = OpponentStats(agent_id, d.get("handle", ""))
                    s.total_hands = d.get("total_hands", 0)
                    s.vpip_opportunities = d.get("vpip_opps", 0)
                    s.vpip_actions = d.get("vpip_actions", 0)
                    s.pfr_opportunities = d.get("pfr_opps", 0)
                    s.pfr_actions = d.get("pfr_actions", 0)
                    s.three_bet_opps = d.get("three_bet_opps", 0)
                    s.three_bet_actions = d.get("three_bet_actions", 0)
                    s.fold_to_3bet_opps = d.get("fold_to_3bet_opps", 0)
                    s.fold_to_3bet_actions = d.get("fold_to_3bet_actions", 0)
                    s.cbet_opportunities = d.get("cbet_opps", 0)
                    s.cbet_actions = d.get("cbet_actions", 0)
                    s.fold_to_cbet_opps = d.get("fold_to_cbet_opps", 0)
                    s.fold_to_cbet_actions = d.get("fold_to_cbet_actions", 0)
                    s.aggressive_actions = d.get("agg_actions", 0)
                    s.passive_actions = d.get("passive_actions", 0)
                    s.showdowns = d.get("showdowns", 0)
                    s.showdown_wins = d.get("showdown_wins", 0)
                    self.players[agent_id] = s
        except Exception:
            pass

    def save(self) -> None:
        try:
            p = Path(self.storage_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {
                agent_id: {
                    "handle": s.handle,
                    "total_hands": s.total_hands,
                    "vpip_opps": s.vpip_opportunities,
                    "vpip_actions": s.vpip_actions,
                    "pfr_opps": s.pfr_opportunities,
                    "pfr_actions": s.pfr_actions,
                    "three_bet_opps": s.three_bet_opps,
                    "three_bet_actions": s.three_bet_actions,
                    "fold_to_3bet_opps": s.fold_to_3bet_opps,
                    "fold_to_3bet_actions": s.fold_to_3bet_actions,
                    "cbet_opps": s.cbet_opportunities,
                    "cbet_actions": s.cbet_actions,
                    "fold_to_cbet_opps": s.fold_to_cbet_opps,
                    "fold_to_cbet_actions": s.fold_to_cbet_actions,
                    "agg_actions": s.aggressive_actions,
                    "passive_actions": s.passive_actions,
                    "showdowns": s.showdowns,
                    "showdown_wins": s.showdown_wins,
                }
                for agent_id, s in self.players.items()
            }
            p.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def get_or_create(self, agent_id: str, handle: str = "") -> OpponentStats:
        if agent_id not in self.players:
            self.players[agent_id] = OpponentStats(agent_id, handle)
        elif handle and not self.players[agent_id].handle:
            self.players[agent_id].handle = handle
        return self.players[agent_id]

    def get(self, agent_id: str) -> Optional[OpponentStats]:
        return self.players.get(agent_id)

    def get_archetype(self, agent_id: str) -> str:
        stats = self.players.get(agent_id)
        if stats is None:
            return "Unknown"
        return stats.archetype

    def get_fold_to_cbet(self, agent_id: str) -> str:
        stats = self.players.get(agent_id)
        if stats is None:
            return "unknown"
        return stats.fold_to_cbet_category

    # ─── Recording methods ─────────────────────────────────────────

    def record_vpip_opportunity(self, agent_id: str, did_vpip: bool) -> None:
        s = self.get_or_create(agent_id)
        s.vpip_opportunities += 1
        s.total_hands = max(s.total_hands, s.vpip_opportunities)
        if did_vpip:
            s.vpip_actions += 1

    def record_pfr(self, agent_id: str, did_raise: bool) -> None:
        s = self.get_or_create(agent_id)
        s.pfr_opportunities += 1
        if did_raise:
            s.pfr_actions += 1

    def record_three_bet(self, agent_id: str, did_3bet: bool) -> None:
        s = self.get_or_create(agent_id)
        s.three_bet_opps += 1
        if did_3bet:
            s.three_bet_actions += 1

    def record_fold_to_3bet(self, agent_id: str, folded: bool) -> None:
        s = self.get_or_create(agent_id)
        s.fold_to_3bet_opps += 1
        if folded:
            s.fold_to_3bet_actions += 1

    def record_cbet(self, agent_id: str, did_cbet: bool) -> None:
        s = self.get_or_create(agent_id)
        s.cbet_opportunities += 1
        if did_cbet:
            s.cbet_actions += 1

    def record_fold_to_cbet(self, agent_id: str, folded: bool) -> None:
        s = self.get_or_create(agent_id)
        s.fold_to_cbet_opps += 1
        if folded:
            s.fold_to_cbet_actions += 1

    def record_action(self, agent_id: str, action_type: str) -> None:
        """Record aggressive or passive action."""
        s = self.get_or_create(agent_id)
        aggressive = {"bet", "raise", "all-in", "all_in", "allin"}
        passive = {"call", "check", "fold"}
        if action_type in aggressive:
            s.aggressive_actions += 1
        elif action_type in passive:
            s.passive_actions += 1

    def record_showdown(self, agent_id: str, won: bool) -> None:
        s = self.get_or_create(agent_id)
        s.showdowns += 1
        if won:
            s.showdown_wins += 1

    def sync_to_db(self, db) -> None:
        """Sync all opponent data to SQLite database."""
        for agent_id, stats in self.players.items():
            if stats.total_hands == 0:
                continue
            db.upsert_opponent(
                agent_id,
                handle=stats.handle,
                total_hands=stats.total_hands,
                vpip_opps=stats.vpip_opportunities,
                vpip_actions=stats.vpip_actions,
                pfr_opps=stats.pfr_opportunities,
                pfr_actions=stats.pfr_actions,
                three_bet_opps=stats.three_bet_opps,
                three_bet_actions=stats.three_bet_actions,
                fold_to_3bet_opps=stats.fold_to_3bet_opps,
                fold_to_3bet_actions=stats.fold_to_3bet_actions,
                cbet_opps=stats.cbet_opportunities,
                cbet_actions=stats.cbet_actions,
                fold_to_cbet_opps=stats.fold_to_cbet_opps,
                fold_to_cbet_actions=stats.fold_to_cbet_actions,
                agg_actions=stats.aggressive_actions,
                passive_actions=stats.passive_actions,
                showdowns=stats.showdowns,
                showdown_wins=stats.showdown_wins,
                archetype=stats.archetype,
            )

    def load_from_db(self, db) -> None:
        """Load opponent data from SQLite database."""
        opponents = db.get_all_opponents(min_hands=0)
        for o in opponents:
            aid = o["agent_id"]
            s = OpponentStats(aid, o.get("handle", ""))
            s.total_hands = o.get("total_hands", 0)
            s.vpip_opportunities = o.get("vpip_opps", 0)
            s.vpip_actions = o.get("vpip_actions", 0)
            s.pfr_opportunities = o.get("pfr_opps", 0)
            s.pfr_actions = o.get("pfr_actions", 0)
            s.three_bet_opps = o.get("three_bet_opps", 0)
            s.three_bet_actions = o.get("three_bet_actions", 0)
            s.fold_to_3bet_opps = o.get("fold_to_3bet_opps", 0)
            s.fold_to_3bet_actions = o.get("fold_to_3bet_actions", 0)
            s.cbet_opportunities = o.get("cbet_opps", 0)
            s.cbet_actions = o.get("cbet_actions", 0)
            s.fold_to_cbet_opps = o.get("fold_to_cbet_opps", 0)
            s.fold_to_cbet_actions = o.get("fold_to_cbet_actions", 0)
            s.aggressive_actions = o.get("agg_actions", 0)
            s.passive_actions = o.get("passive_actions", 0)
            s.showdowns = o.get("showdowns", 0)
            s.showdown_wins = o.get("showdown_wins", 0)
            self.players[aid] = s


# ─── Strategy adjustments based on opponent profile ────────────────

def adjust_cbet_freq(base_freq: float, opponent_fold_to_cbet: str) -> float:
    """Adjust cbet frequency based on opponent's fold-to-cbet tendency."""
    adjustments = {
        "high_fold": 0.15,   # Cbet more vs players who fold too much
        "normal": 0.0,
        "sticky": -0.10,     # Cbet less vs sticky players
        "unknown": 0.0,
    }
    return max(0.2, min(0.9, base_freq + adjustments.get(opponent_fold_to_cbet, 0.0)))


def adjust_open_range(position: str, archetypes: dict[str, str]) -> bool:
    """Whether to expand opening range based on player types at table."""
    if not archetypes:
        return False
    nits_weak = sum(1 for a in archetypes.values() if a in ("Nit", "Passive Fish", "Calling Station", "Whale"))
    total = len(archetypes)
    return nits_weak >= total * 0.4


def adjust_bluff_freq(base_freq: float, archetype: str) -> float:
    """Adjust bluff frequency based on opponent archetype."""
    adjustments = {
        "Nit": 0.15,
        "TAG": 0.0,
        "LAG": -0.10,
        "Maniac": -0.15,
        "Passive Fish": 0.05,
        "Calling Station": -0.10,
        "Whale": -0.15,
        "Unknown": 0.0,
    }
    return max(0.05, min(0.5, base_freq + adjustments.get(archetype, 0.0)))


def value_bet_thinner(archetype: str) -> bool:
    """Can we value bet thinner against this player type?"""
    return archetype in ("Passive Fish", "Maniac", "LAG", "Whale", "Calling Station", "Unknown")
