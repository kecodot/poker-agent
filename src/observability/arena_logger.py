"""Arena match observability system.

Captures every real arena hand, session summaries, and errors.
Supports rotation, compression, and daily reporting.

Usage:
    from src.observability import ArenaMatchLogger

    logger = ArenaMatchLogger()

    # Session lifecycle
    logger.start_session(competition_id, match_id)

    # Log every decision
    logger.log_decision(table, action)

    # Log hand result (when hand completes)
    logger.log_hand_result(hand_id, result, bb_won)

    # Log errors
    logger.log_error("invalid_state", "missing hole cards", raw=table)

    # End session
    logger.end_session(final_stats)

    # Generate daily report
    logger.generate_daily_report()
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MATCHES_DIR = PROJECT_ROOT / "arena_matches"
SESSIONS_DIR = PROJECT_ROOT / "arena_sessions"
ERRORS_DIR = PROJECT_ROOT / "arena_errors"
ARCHIVE_DIR = PROJECT_ROOT / "arena_matches" / "archive"
REPORTS_DIR = PROJECT_ROOT / "arena_reports"

# Rotation: new file daily, compress after 7 days
ROTATION_AGE_DAYS = 1
COMPRESSION_AGE_DAYS = 7
ARCHIVE_AGE_DAYS = 30
MAX_UNCOMPRESSED_FILES = 14

_global_logger: Optional["ArenaMatchLogger"] = None


def get_logger() -> "ArenaMatchLogger":
    global _global_logger
    if _global_logger is None:
        _global_logger = ArenaMatchLogger()
    return _global_logger


class ArenaMatchLogger:
    """Observability logger for live arena matches."""

    def __init__(self):
        self._session_id: Optional[str] = None
        self._competition_id: Optional[str] = None
        self._match_id: Optional[str] = None
        self._session_start: Optional[float] = None
        self._hands_in_session: list[dict] = []
        self._errors_in_session: list[dict] = []
        self._opponents_seen: dict[str, int] = {}
        self._strategy_usage: dict[str, int] = {"limp_value": 0, "raise_exploit": 0, "hybrid": 0}
        self._stack_history: list[float] = []

        # Ensure directories exist
        for d in (MATCHES_DIR, SESSIONS_DIR, ERRORS_DIR, ARCHIVE_DIR, REPORTS_DIR):
            d.mkdir(parents=True, exist_ok=True)

        # Run maintenance on init
        self._maintenance()

    # ─── Session lifecycle ──────────────────────────────────────────────

    def start_session(self, competition_id: str, match_id: str) -> str:
        """Begin a new arena session. Returns session_id."""
        self._session_id = f"{match_id}_{int(time.time())}"
        self._competition_id = competition_id
        self._match_id = match_id
        self._session_start = time.time()
        self._hands_in_session = []
        self._errors_in_session = []
        self._opponents_seen = {}
        self._strategy_usage = {"limp_value": 0, "raise_exploit": 0, "hybrid": 0}
        self._stack_history = []
        return self._session_id

    def end_session(self, final_stats: Optional[dict] = None) -> dict:
        """Close the session and write summary."""
        duration_s = time.time() - (self._session_start or time.time())
        total_hands = len(self._hands_in_session)

        # Calculate BB won
        total_bb_won = 0.0
        for h in self._hands_in_session:
            total_bb_won += float(h.get("bb_won") or 0)

        bb_per_100 = (total_bb_won / total_hands * 100) if total_hands > 0 else 0.0

        # Build session summary
        summary = {
            "session_id": self._session_id,
            "competition_id": self._competition_id,
            "match_id": self._match_id,
            "started_at": datetime.fromtimestamp(self._session_start or 0, tz=timezone.utc).isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(duration_s, 1),
            "total_hands": total_hands,
            "total_bb_won": round(total_bb_won, 2),
            "bb_per_100": round(bb_per_100, 2),
            "opponent_breakdown": dict(self._opponents_seen),
            "strategy_usage": dict(self._strategy_usage),
            "error_count": len(self._errors_in_session),
            "errors_by_type": {},
        }

        # Error type breakdown
        for e in self._errors_in_session:
            etype = e.get("error_type", "unknown")
            summary["errors_by_type"][etype] = summary["errors_by_type"].get(etype, 0) + 1

        # Merge external stats
        if final_stats:
            summary["arena_stats"] = final_stats

        # Write to disk
        session_file = SESSIONS_DIR / f"{self._session_id}.json"
        session_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

        # Flush hands JSONL
        if self._hands_in_session:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            hands_file = MATCHES_DIR / f"{date_str}.jsonl"
            with open(hands_file, "a") as f:
                for h in self._hands_in_session:
                    f.write(json.dumps(h, ensure_ascii=False) + "\n")

        # Flush errors JSONL
        if self._errors_in_session:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            err_file = ERRORS_DIR / f"{date_str}.jsonl"
            with open(err_file, "a") as f:
                for e in self._errors_in_session:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

        return summary

    # ─── Decision logging ───────────────────────────────────────────────

    def log_decision(self, table: dict, action: dict) -> None:
        """Record a single decision with full context.

        Called after every decide() → POST /texas/action.
        """
        ts = datetime.now(timezone.utc).isoformat()

        self_seat_num = table.get("selfSeatNumber")
        seats = table.get("seats") or []
        self_seat = next((s for s in seats if s.get("seatNumber") == self_seat_num), {})

        hole = list(self_seat.get("holeCards") or [])
        board = list(table.get("boardCards") or [])

        # Opponent IDs at the table
        opponent_ids = [
            s.get("agentId", "") for s in seats
            if s.get("seatNumber") != self_seat_num and s.get("agentId")
        ]
        for oid in opponent_ids:
            self._opponents_seen[oid] = self._opponents_seen.get(oid, 0) + 1

        # Strategy usage tracking
        weights = action.get("strategy_weights") or {}
        dominant = max(weights, key=weights.get) if weights else "hybrid"
        self._strategy_usage[dominant] = self._strategy_usage.get(dominant, 0) + 1

        my_stack = int(self_seat.get("stackChips") or 0)
        self._stack_history.append(my_stack)

        total_committed = int(self_seat.get("totalCommittedChips") or 0)

        # Action size in BB
        bb = int(table.get("bigBlindChips") or 2)
        action_amount = action.get("amount")
        action_size_bb = round(action_amount / bb, 1) if action_amount else None

        record = {
            "ts": ts,
            "session_id": self._session_id,
            "match_id": self._match_id,
            "competition_id": self._competition_id,
            "table_id": table.get("tableId", "?"),
            "hand_id": table.get("handId") or table.get("tableId", "?"),
            "street": table.get("street"),
            "position": table.get("selfPosition") or str(self_seat_num),
            "seat_number": self_seat_num,
            "hole_cards": hole,
            "board_cards": board,
            "pot_size": table.get("potChips", 0),
            "stack_size": my_stack,
            "total_committed": total_committed,
            "effective_stack_bb": None,
            "opponent_ids": opponent_ids[:6],
            "opponent_count": len(opponent_ids),
            "strategy_weights": weights,
            "blend_method": action.get("blend_method"),
            "chosen_action": action.get("action"),
            "action_size": action_amount,
            "action_size_bb": action_size_bb,
            "reasoning": (action.get("reasoning") or "")[:150],
            "message": (action.get("message") or "")[:200],
            "allowed_actions": (table.get("allowedActions") or {}).get("availableActions", []),
            "call_chips": (table.get("allowedActions") or {}).get("callChips", 0),
            "big_blind": bb,
            "result": None,
            "bb_won": None,
        }

        # Effective stack
        active_stacks = [
            int(s.get("stackChips") or 0) for s in seats
            if s.get("seatNumber") != self_seat_num and (s.get("stackChips") or 0) > 0
        ]
        if active_stacks:
            eff = min(my_stack, min(active_stacks))
            record["effective_stack_bb"] = round(eff / max(bb, 1), 1)

        self._hands_in_session.append(record)

    def log_hand_result(self, hand_id: str, result: str, bb_won: float) -> None:
        """Attach result to the most recent matching hand record.

        Called when a hand completes (hero wins/loses/pushes).
        """
        for h in reversed(self._hands_in_session):
            if h.get("hand_id") == hand_id and h.get("result") is None:
                h["result"] = result
                h["bb_won"] = round(bb_won, 2)
                return

    # ─── Error logging ──────────────────────────────────────────────────

    def log_error(
        self,
        error_type: str,
        message: str,
        table: Optional[dict] = None,
        raw: Any = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Log an arena error event.

        error_type: one of 'invalid_state', 'timeout', 'reconnect', 'failed_action'
        """
        ts = datetime.now(timezone.utc).isoformat()
        record = {
            "ts": ts,
            "session_id": self._session_id,
            "match_id": self._match_id,
            "error_type": error_type,
            "message": message,
            "table_id": (table or {}).get("tableId") if table else None,
            "street": (table or {}).get("street") if table else None,
            "exception": str(exception) if exception else None,
            "raw_summary": str(raw)[:500] if raw else None,
        }
        self._errors_in_session.append(record)

        # Write immediately
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        err_file = ERRORS_DIR / f"{date_str}.jsonl"
        try:
            with open(err_file, "a") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # ─── Compression and rotation ───────────────────────────────────────

    def _maintenance(self) -> None:
        """Run log rotation, compression, and archiving."""
        now = time.time()
        try:
            for pattern, directory in [
                ("*.jsonl", MATCHES_DIR),
                ("*.jsonl", ERRORS_DIR),
            ]:
                for f in sorted(directory.glob(pattern)):
                    if f.name.startswith("archive"):
                        continue
                    age_days = (now - f.stat().st_mtime) / 86400.0

                    # Compress old files
                    if age_days > COMPRESSION_AGE_DAYS and not f.name.endswith(".gz"):
                        self._compress_file(f)

                    # Archive very old files
                    elif age_days > ARCHIVE_AGE_DAYS:
                        self._archive_file(f)

            # Rotate if too many uncompressed files
            uncompressed = sorted([
                f for f in MATCHES_DIR.glob("*.jsonl")
                if not f.name.startswith("archive")
            ])
            if len(uncompressed) > MAX_UNCOMPRESSED_FILES:
                for f in uncompressed[:-MAX_UNCOMPRESSED_FILES]:
                    if not f.name.endswith(".gz"):
                        self._compress_file(f)
        except Exception:
            pass

    @staticmethod
    def _compress_file(filepath: Path) -> Optional[Path]:
        """Gzip a JSONL file and remove the original."""
        gz_path = filepath.with_suffix(filepath.suffix + ".gz")
        if gz_path.exists():
            return gz_path
        try:
            with open(filepath, "rb") as f_in:
                with gzip.open(gz_path, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            filepath.unlink()
            return gz_path
        except OSError:
            return None

    @staticmethod
    def _archive_file(filepath: Path) -> None:
        """Move a file to the archive directory."""
        try:
            dest = ARCHIVE_DIR / filepath.name
            shutil.move(str(filepath), str(dest))
        except OSError:
            pass

    # ─── Daily report generation ────────────────────────────────────────

    def generate_daily_report(self, date_str: Optional[str] = None) -> Path:
        """Generate arena_daily_report.md from today's (or specified) logs.

        Returns path to the generated report.
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        hands_file = MATCHES_DIR / f"{date_str}.jsonl"
        err_file = ERRORS_DIR / f"{date_str}.jsonl"

        hands = self._load_jsonl(hands_file)
        errors = self._load_jsonl(err_file)

        report_path = REPORTS_DIR / f"arena_daily_report_{date_str}.md"
        report = self._build_report(date_str, hands, errors)
        report_path.write_text(report)
        return report_path

    @staticmethod
    def _load_jsonl(path: Path) -> list[dict]:
        """Load JSONL (possibly gzipped)."""
        records = []
        if not path.exists():
            gz_path = path.with_suffix(path.suffix + ".gz")
            if not gz_path.exists():
                return records
            path = gz_path

        try:
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(str(path), "rt") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except (OSError, EOFError):
            pass
        return records

    def _build_report(self, date_str: str, hands: list[dict], errors: list[dict]) -> str:
        """Build the daily report markdown."""
        n = len(hands)
        if n == 0:
            return f"# Arena Daily Report — {date_str}\n\nNo hands recorded today.\n"

        # BB/100
        total_bb = sum(float(h.get("bb_won") or 0) for h in hands)
        known_results = [h for h in hands if h.get("result") is not None]
        n_results = len(known_results) if known_results else n
        bb_per_100 = (total_bb / n_results * 100) if n_results > 0 else 0.0

        # Win rate
        wins = sum(1 for h in hands if h.get("result") == "win")
        losses = sum(1 for h in hands if h.get("result") == "loss")
        pushes = sum(1 for h in hands if h.get("result") == "push")
        win_rate = wins / max(n_results, 1)

        # Action distribution
        actions: dict[str, int] = {}
        for h in hands:
            a = h.get("chosen_action", "?")
            actions[a] = actions.get(a, 0) + 1

        # Strategy usage
        strategy: dict[str, int] = {}
        for h in hands:
            w = h.get("strategy_weights") or {}
            if w:
                dominant = max(w, key=w.get)
                strategy[dominant] = strategy.get(dominant, 0) + 1

        # Position breakdown
        by_pos: dict[str, dict] = {}
        for h in hands:
            pos = h.get("position", "?")
            if pos not in by_pos:
                by_pos[pos] = {"count": 0, "bb_won": 0.0, "actions": {}}
            by_pos[pos]["count"] += 1
            by_pos[pos]["bb_won"] += float(h.get("bb_won") or 0)
            a = h.get("chosen_action", "?")
            by_pos[pos]["actions"][a] = by_pos[pos]["actions"].get(a, 0) + 1

        # Street breakdown
        by_street: dict[str, int] = {}
        for h in hands:
            s = h.get("street", "?")
            by_street[s] = by_street.get(s, 0) + 1

        # Opponent frequency
        opponents: dict[str, int] = {}
        for h in hands:
            for oid in h.get("opponent_ids", []):
                opponents[oid] = opponents.get(oid, 0) + 1
        top_opponents = sorted(opponents.items(), key=lambda x: -x[1])[:5]
        most_freq_opp = sorted(opponents.items(), key=lambda x: -x[1])

        # Build report
        lines = [
            f"# Arena Daily Report — {date_str}",
            "",
            f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Hands | {n} |",
            f"| BB/100 | **{bb_per_100:+.2f}** |",
            f"| Total BB Won | {total_bb:+.2f} |",
            f"| Win Rate | {win_rate:.1%} ({wins}W / {losses}L / {pushes}P) |",
            f"| Errors | {len(errors)} |",
            "",
            "## Action Distribution",
            "",
        ]

        for act in ["fold", "check", "call", "bet", "raise", "all-in"]:
            count = actions.get(act, 0)
            if count > 0:
                lines.append(f"- **{act}**: {count} ({count/max(n,1)*100:.1f}%)")

        lines += [
            "",
            "## Strategy Usage",
            "",
        ]
        for sname, count in sorted(strategy.items(), key=lambda x: -x[1]):
            lines.append(f"- **{sname}**: {count} ({count/max(n,1)*100:.1f}%)")

        lines += [
            "",
            "## Position Performance",
            "",
            "| Position | Hands | BB Won | BB/100 | Top Action |",
            "|----------|-------|--------|--------|------------|",
        ]
        for pos in ["UTG", "MP", "CO", "BTN", "SB", "BB"]:
            if pos in by_pos:
                d = by_pos[pos]
                c = d["count"]
                bb = d["bb_won"]
                bb100 = (bb / c * 100) if c > 0 else 0
                top_act = max(d["actions"], key=d["actions"].get) if d["actions"] else "?"
                lines.append(f"| {pos} | {c} | {bb:+.1f} | {bb100:+.1f} | {top_act} |")

        lines += [
            "",
            "## Street Distribution",
            "",
        ]
        for street in ["Preflop", "Flop", "Turn", "River"]:
            count = by_street.get(street, 0)
            if count > 0:
                lines.append(f"- **{street}**: {count} ({count/max(n,1)*100:.1f}%)")

        lines += [
            "",
            "## Top Opponents",
            "",
            "| Opponent | Hands Seen |",
            "|----------|-----------|",
        ]
        for oid, count in top_opponents:
            lines.append(f"| {oid[:30]} | {count} |")

        if most_freq_opp:
            most_freq = most_freq_opp[0]
            lines += [
                "",
                f"**Most frequent opponent:** `{most_freq[0]}` ({most_freq[1]} hands)",
            ]

        if errors:
            lines += [
                "",
                "## Errors",
                "",
            ]
            err_types: dict[str, int] = {}
            for e in errors:
                t = e.get("error_type", "unknown")
                err_types[t] = err_types.get(t, 0) + 1
            for etype, count in err_types.items():
                lines.append(f"- **{etype}**: {count}")

        return "\n".join(lines) + "\n"
