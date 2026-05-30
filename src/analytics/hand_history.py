"""Hand history recorder — JSON logging of every hand played.

Records:
  - Hand ID, timestamp, competition ID
  - Hole cards, board cards
  - Position, stack sizes
  - Actions taken (with reasoning)
  - Result (chip delta)
  - Opponent information

Used by:
  - Strategy optimizer for finding leaks
  - Session review
  - Opponent model data enrichment
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class HandHistory:
    """Records and queries hand histories."""

    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.current_session_file = self.log_dir / f"session_{int(time.time())}.jsonl"
        self._buffer: list[dict] = []
        self._buffer_size = 10

    def record_hand(
        self,
        hand_id: str,
        competition_id: str,
        table_id: str,
        hole_cards: list[str],
        board_cards: list[str],
        position: str,
        seat_number: int,
        stack_start: int,
        stack_end: int,
        actions: list[dict],
        result_chips: int,
        street_reached: str,
        opponents: list[dict],
        reasoning_summary: str = "",
    ) -> None:
        """Record a complete hand."""
        entry = {
            "hand_id": hand_id,
            "competition_id": competition_id,
            "table_id": table_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hole_cards": hole_cards,
            "board_cards": board_cards,
            "position": position,
            "seat_number": seat_number,
            "stack_start": stack_start,
            "stack_end": stack_end,
            "chip_delta": result_chips,
            "street_reached": street_reached,
            "actions": actions,
            "opponents": opponents,
            "reasoning_summary": reasoning_summary,
        }
        self._buffer.append(entry)
        if len(self._buffer) >= self._buffer_size:
            self.flush()

    def record_action(
        self,
        hand_id: str,
        street: str,
        action: str,
        amount: Optional[int],
        reasoning: str,
        equity: float,
        pot_odds: float,
    ) -> dict:
        """Create an action record."""
        return {
            "street": street,
            "action": action,
            "amount": amount,
            "reasoning": reasoning,
            "equity": equity,
            "pot_odds": pot_odds,
            "timestamp_ms": int(time.time() * 1000),
        }

    def flush(self) -> None:
        """Write buffered hands to disk."""
        if not self._buffer:
            return
        try:
            with open(self.current_session_file, "a") as f:
                for entry in self._buffer:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._buffer.clear()
        except Exception as e:
            print(f"[hand-history] flush error: {e}")

    def get_recent_hands(self, n: int = 100) -> list[dict]:
        """Load the most recent N hands from disk."""
        self.flush()
        hands: list[dict] = []
        try:
            for session_file in sorted(self.log_dir.glob("session_*.jsonl"),
                                       reverse=True):
                if len(hands) >= n:
                    break
                with open(session_file) as f:
                    lines = f.readlines()
                for line in reversed(lines):
                    if len(hands) >= n:
                        break
                    try:
                        hands.append(json.loads(line.strip()))
                    except Exception:
                        pass
        except Exception:
            pass
        return hands

    def get_hands_by_position(self, position: str, limit: int = 500) -> list[dict]:
        """Get hands played from a specific position."""
        recent = self.get_recent_hands(limit)
        return [h for h in recent if h.get("position") == position]

    def get_losing_hands(self, min_loss_chips: int = -5, limit: int = 100) -> list[dict]:
        """Get hands where we lost >= min_loss_chips."""
        recent = self.get_recent_hands(limit)
        losing = [h for h in recent if h.get("chip_delta", 0) <= min_loss_chips]
        losing.sort(key=lambda h: h.get("chip_delta", 0))
        return losing

    def get_hand_count(self) -> int:
        """Count total recorded hands."""
        self.flush()
        count = 0
        try:
            for session_file in self.log_dir.glob("session_*.jsonl"):
                with open(session_file) as f:
                    count += sum(1 for _ in f)
        except Exception:
            pass
        return count

    def get_session_stats(self) -> dict:
        """Aggregate statistics for the current session."""
        hands = self.get_recent_hands(1000)
        if not hands:
            return {"total_hands": 0}

        total = len(hands)
        wins = sum(1 for h in hands if h.get("chip_delta", 0) > 0)
        losses = sum(1 for h in hands if h.get("chip_delta", 0) < 0)
        pushes = total - wins - losses
        net_chips = sum(h.get("chip_delta", 0) for h in hands)
        avg_delta = net_chips / max(total, 1)

        # By position
        by_pos: dict[str, dict] = {}
        for h in hands:
            pos = h.get("position", "?")
            d = by_pos.setdefault(pos, {"count": 0, "net": 0})
            d["count"] += 1
            d["net"] += h.get("chip_delta", 0)

        return {
            "total_hands": total,
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "win_rate": wins / max(total, 1),
            "net_chips": net_chips,
            "avg_chip_delta": round(avg_delta, 1),
            "by_position": {p: {"count": d["count"],
                                "net": d["net"],
                                "avg": round(d["net"] / max(d["count"], 1), 1)}
                           for p, d in by_pos.items()},
        }
