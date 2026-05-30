"""SQLite-based hand history database.

Tables:
  - sessions: Agent session metadata
  - hands: Individual hand records with results
  - actions: Per-street action records with decision context
  - opponents: Long-term opponent profiles
  - strategy_versions: Parameter snapshot for each version

Usage:
  db = HandDatabase("data/hands.db")
  db.record_session(...)
  db.record_hand(...)
  db.record_action(...)
  db.get_recent_hands(100)
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    competition_id TEXT NOT NULL,
    agent_handle TEXT NOT NULL,
    strategy_version TEXT NOT NULL DEFAULT 'v1',
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    hands_played INTEGER DEFAULT 0,
    total_chips_won INTEGER DEFAULT 0,
    bb_per_100 REAL,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS hands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id TEXT UNIQUE NOT NULL,
    session_id TEXT NOT NULL,
    table_id TEXT NOT NULL,
    competition_id TEXT NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    position TEXT NOT NULL,
    seat_number INTEGER NOT NULL,
    hole_cards TEXT NOT NULL,
    board_cards TEXT NOT NULL,
    street_reached TEXT NOT NULL,
    stack_start INTEGER NOT NULL,
    stack_end INTEGER NOT NULL,
    chip_delta INTEGER NOT NULL,
    pot_at_end INTEGER DEFAULT 0,
    result TEXT NOT NULL DEFAULT '',  -- win / loss / push
    n_opponents INTEGER DEFAULT 0,
    opponent_ids TEXT DEFAULT '[]',
    big_blind INTEGER DEFAULT 2,
    decision_time_ms REAL DEFAULT 0,
    equity_final REAL,
    notes TEXT DEFAULT '',
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hand_id TEXT NOT NULL,
    street TEXT NOT NULL,
    action TEXT NOT NULL,
    amount INTEGER,
    reasoning TEXT DEFAULT '',
    equity REAL,
    pot_odds REAL,
    pot_chips INTEGER DEFAULT 0,
    call_chips INTEGER DEFAULT 0,
    stack_chips INTEGER DEFAULT 0,
    timestamp_ms INTEGER NOT NULL,
    position TEXT DEFAULT '',
    board_at_action TEXT DEFAULT '[]',
    FOREIGN KEY (hand_id) REFERENCES hands(hand_id)
);

CREATE TABLE IF NOT EXISTS opponents (
    agent_id TEXT PRIMARY KEY,
    handle TEXT DEFAULT '',
    total_hands INTEGER DEFAULT 0,

    -- Preflop stats
    vpip_opps INTEGER DEFAULT 0,
    vpip_actions INTEGER DEFAULT 0,
    pfr_opps INTEGER DEFAULT 0,
    pfr_actions INTEGER DEFAULT 0,
    three_bet_opps INTEGER DEFAULT 0,
    three_bet_actions INTEGER DEFAULT 0,
    fold_to_3bet_opps INTEGER DEFAULT 0,
    fold_to_3bet_actions INTEGER DEFAULT 0,

    -- Postflop
    cbet_opps INTEGER DEFAULT 0,
    cbet_actions INTEGER DEFAULT 0,
    fold_to_cbet_opps INTEGER DEFAULT 0,
    fold_to_cbet_actions INTEGER DEFAULT 0,

    -- Aggression
    agg_actions INTEGER DEFAULT 0,
    passive_actions INTEGER DEFAULT 0,

    -- Showdown
    showdowns INTEGER DEFAULT 0,
    showdown_wins INTEGER DEFAULT 0,

    -- Classification
    archetype TEXT DEFAULT 'Unknown',
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,

    -- Meta
    total_won_from_us INTEGER DEFAULT 0,
    total_lost_to_us INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS strategy_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    bb_per_100 REAL,
    hands_evaluated INTEGER DEFAULT 0,
    roi REAL,
    created_at TIMESTAMP NOT NULL,
    is_active INTEGER DEFAULT 0,
    notes TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_hands_session ON hands(session_id);
CREATE INDEX IF NOT EXISTS idx_hands_position ON hands(position);
CREATE INDEX IF NOT EXISTS idx_hands_timestamp ON hands(timestamp);
CREATE INDEX IF NOT EXISTS idx_actions_hand ON actions(hand_id);
CREATE INDEX IF NOT EXISTS idx_actions_street ON actions(street);
CREATE INDEX IF NOT EXISTS idx_opponents_archetype ON opponents(archetype);
CREATE INDEX IF NOT EXISTS idx_strategy_version ON strategy_versions(version);
"""


class HandDatabase:
    """SQLite database for hand history, opponents, and strategy versions."""

    def __init__(self, db_path: str = "data/hands.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(SCHEMA)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ─── Sessions ──────────────────────────────────────────────────

    def start_session(self, session_id: str, competition_id: str,
                      agent_handle: str = "poker-agent",
                      strategy_version: str = "v1") -> int:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO sessions (session_id, competition_id, agent_handle,
               strategy_version, started_at, status)
               VALUES (?, ?, ?, ?, ?, 'active')
               ON CONFLICT(session_id) DO UPDATE SET status='active',
               started_at=excluded.started_at""",
            (session_id, competition_id, agent_handle,
             strategy_version, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()
        return conn.execute("SELECT id FROM sessions WHERE session_id=?",
                            (session_id,)).fetchone()["id"]

    def end_session(self, session_id: str, hands_played: int = 0,
                    total_chips: int = 0, bb_per_100: float = 0.0) -> None:
        conn = self._get_conn()
        conn.execute(
            """UPDATE sessions SET ended_at=?, hands_played=?,
               total_chips_won=?, bb_per_100=?, status='completed'
               WHERE session_id=?""",
            (datetime.now(timezone.utc).isoformat(), hands_played,
             total_chips, bb_per_100, session_id)
        )
        conn.commit()

    # ─── Hands ─────────────────────────────────────────────────────

    def record_hand(self, hand_id: str, session_id: str, table_id: str,
                    competition_id: str, position: str, seat_number: int,
                    hole_cards: list[str], board_cards: list[str],
                    street_reached: str, stack_start: int, stack_end: int,
                    chip_delta: int, pot_at_end: int = 0,
                    n_opponents: int = 0, opponent_ids: list[str] = None,
                    big_blind: int = 2, decision_time_ms: float = 0,
                    equity_final: float = None, notes: str = "") -> None:
        conn = self._get_conn()
        result = "win" if chip_delta > 0 else ("loss" if chip_delta < 0 else "push")
        conn.execute(
            """INSERT OR REPLACE INTO hands
               (hand_id, session_id, table_id, competition_id, timestamp,
                position, seat_number, hole_cards, board_cards, street_reached,
                stack_start, stack_end, chip_delta, pot_at_end, result,
                n_opponents, opponent_ids, big_blind, decision_time_ms,
                equity_final, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (hand_id, session_id, table_id, competition_id,
             datetime.now(timezone.utc).isoformat(), position, seat_number,
             json.dumps(hole_cards), json.dumps(board_cards), street_reached,
             stack_start, stack_end, chip_delta, pot_at_end, result,
             n_opponents, json.dumps(opponent_ids or []), big_blind,
             decision_time_ms, equity_final, notes)
        )
        conn.commit()

    def record_action(self, hand_id: str, street: str, action: str,
                      amount: int = None, reasoning: str = "",
                      equity: float = None, pot_odds: float = None,
                      pot_chips: int = 0, call_chips: int = 0,
                      stack_chips: int = 0, position: str = "",
                      board_at_action: list[str] = None) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO actions (hand_id, street, action, amount, reasoning,
               equity, pot_odds, pot_chips, call_chips, stack_chips,
               timestamp_ms, position, board_at_action)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (hand_id, street, action, amount, reasoning, equity, pot_odds,
             pot_chips, call_chips, stack_chips, int(time.time() * 1000),
             position, json.dumps(board_at_action or []))
        )
        conn.commit()

    def get_recent_hands(self, n: int = 100) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM hands ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["hole_cards"] = json.loads(d.get("hole_cards", "[]"))
            d["board_cards"] = json.loads(d.get("board_cards", "[]"))
            d["opponent_ids"] = json.loads(d.get("opponent_ids", "[]"))
            result.append(d)
        return result

    def get_hands_by_position(self, position: str, limit: int = 500) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM hands WHERE position=? ORDER BY timestamp DESC LIMIT ?",
            (position, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_hand_count(self) -> int:
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) as c FROM hands").fetchone()["c"]

    def get_total_hands_in_range(self, limit: int = 100) -> int:
        conn = self._get_conn()
        return min(conn.execute("SELECT COUNT(*) as c FROM hands").fetchone()["c"], limit)

    # ─── Analytics queries ─────────────────────────────────────────

    def get_stats_for_n_hands(self, n: int) -> dict:
        """Compute BB/100, ROI, VPIP, PFR, 3BET, etc. for last N hands."""
        conn = self._get_conn()
        hands = conn.execute(
            "SELECT * FROM hands ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()
        if not hands:
            return {"hands": 0}

        total = len(hands)
        wins = sum(1 for h in hands if h["chip_delta"] > 0)
        losses = sum(1 for h in hands if h["chip_delta"] < 0)
        pushes = total - wins - losses
        net_chips = sum(h["chip_delta"] for h in hands)
        big_blinds = sum(max(h["big_blind"], 1) for h in hands)
        avg_bb = big_blinds / total if total else 2
        bb_per_100 = (net_chips / avg_bb) / total * 100

        # Aggregate action stats
        action_stats = {}
        for h in hands:
            acts = conn.execute(
                "SELECT action FROM actions WHERE hand_id=?",
                (h["hand_id"],)
            ).fetchall()
            for a in acts:
                action_stats[a["action"]] = action_stats.get(a["action"], 0) + 1

        total_actions = sum(action_stats.values()) or 1
        vpip_hands = sum(1 for h in hands if h["street_reached"] != "Preflop" or h["chip_delta"] != 0)

        return {
            "hands": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": round(wins / total * 100, 1),
            "net_chips": net_chips,
            "bb_per_100": round(bb_per_100, 1),
            "avg_chip_delta": round(net_chips / total, 1),
            "action_distribution": {
                a: round(c / total_actions * 100, 1) for a, c in action_stats.items()
            },
            "vpip_estimate": round(vpip_hands / total * 100, 1),
        }

    def get_position_stats(self, n: int = 1000) -> dict:
        """Get BB/100 by position."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM hands ORDER BY timestamp DESC LIMIT ?", (n,)
        ).fetchall()

        by_pos: dict[str, dict] = {}
        for r in rows:
            pos = r["position"]
            d = by_pos.setdefault(pos, {"hands": 0, "net_chips": 0, "wins": 0, "losses": 0})
            d["hands"] += 1
            d["net_chips"] += r["chip_delta"]
            if r["chip_delta"] > 0:
                d["wins"] += 1
            elif r["chip_delta"] < 0:
                d["losses"] += 1

        bb = 2.0
        result = {}
        for pos, d in sorted(by_pos.items()):
            result[pos] = {
                "hands": d["hands"],
                "net_chips": d["net_chips"],
                "avg_chip_delta": round(d["net_chips"] / max(d["hands"], 1), 1),
                "win_rate": round(d["wins"] / max(d["hands"], 1) * 100, 1),
                "bb_per_100": round((d["net_chips"] / bb) / max(d["hands"], 1) * 100, 1),
            }
        return result

    def get_street_stats(self, n: int = 1000) -> dict:
        """Get action distribution by street."""
        conn = self._get_conn()
        actions = conn.execute(
            "SELECT street, action, COUNT(*) as cnt FROM actions "
            "WHERE hand_id IN (SELECT hand_id FROM hands ORDER BY timestamp DESC LIMIT ?) "
            "GROUP BY street, action", (n,)
        ).fetchall()

        by_street: dict[str, dict] = {}
        for a in actions:
            s = by_street.setdefault(a["street"], {})
            s[a["action"]] = a["cnt"]
        return by_street

    # ─── Strategy versions ─────────────────────────────────────────

    def save_strategy_version(self, version: str, config: dict,
                              bb_per_100: float = None, roi: float = None,
                              hands_evaluated: int = 0, is_active: bool = False,
                              notes: str = "") -> int:
        conn = self._get_conn()
        if is_active:
            conn.execute("UPDATE strategy_versions SET is_active=0")
        conn.execute(
            """INSERT INTO strategy_versions
               (version, config_json, bb_per_100, hands_evaluated, roi,
                created_at, is_active, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (version, json.dumps(config), bb_per_100, hands_evaluated, roi,
             datetime.now(timezone.utc).isoformat(), 1 if is_active else 0, notes)
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def get_active_strategy(self) -> dict:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM strategy_versions WHERE is_active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            d = dict(row)
            d["config_json"] = json.loads(d.get("config_json", "{}"))
            return d
        return {}

    def get_strategy_ranking(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM strategy_versions ORDER BY bb_per_100 DESC NULLS LAST"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["config_json"] = json.loads(d.get("config_json", "{}"))
            result.append(d)
        return result

    def get_opponent(self, agent_id: str) -> dict:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM opponents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        return dict(row) if row else {}

    def upsert_opponent(self, agent_id: str, **kwargs) -> None:
        conn = self._get_conn()
        existing = conn.execute(
            "SELECT agent_id FROM opponents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k}=?" for k in kwargs)
            conn.execute(
                f"UPDATE opponents SET {sets} WHERE agent_id=?",
                tuple(kwargs.values()) + (agent_id,)
            )
        else:
            kwargs["agent_id"] = agent_id
            kwargs.setdefault("first_seen", datetime.now(timezone.utc).isoformat())
            kwargs.setdefault("last_seen", datetime.now(timezone.utc).isoformat())
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" * len(kwargs))
            conn.execute(
                f"INSERT INTO opponents ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values())
            )
        conn.commit()

    def get_all_opponents(self, min_hands: int = 1) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM opponents WHERE total_hands>=? ORDER BY total_hands DESC",
            (min_hands,)
        ).fetchall()
        return [dict(r) for r in rows]
