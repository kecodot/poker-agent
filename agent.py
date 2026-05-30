"""Bridge module — provides the Agent API that mock.py and arena_client.py expect.

This thin wrapper allows the starter kit's mock and benchmark loop to work
with our agent without modifying their internal imports.
"""

from decide import decide, retrieve_solver_context
from src.agent.main_agent import on_session_end


# Re-export _run_benchmark_loop for mock.py's dry-run
# This is imported late by mock.run_mock_benchmark
import sys
from pathlib import Path

# Add our path for the arena_client imports to work
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from arena_client import (
    ArenaClient,
    ArenaError,
    append_iteration,
    load_state,
    save_state,
)

# Re-create the _run_benchmark_loop function used by both agent.py (starter kit)
# and mock.py. This is the shared benchmark loop.
import time
import random as _random
from typing import Any

FALLBACK_REASONING = '{vr: "std", ke: "legal", pp: "pot control"}'

_ACTION_ALIASES = {"all_in": "all-in", "allin": "all-in"}

POLL_INTERVAL = 1.0
POLL_JITTER = 0.5
STATUS_REFRESH_S = 8.0


def _validate_pending_tables(pending: Any) -> list[dict]:
    if not isinstance(pending, dict):
        return []
    raw = pending.get("tables")
    if raw is None or not isinstance(raw, list):
        return []
    valid = []
    for row in raw:
        if isinstance(row, dict) and isinstance(row.get("tableId"), str) and row["tableId"]:
            valid.append(row)
    return valid


def _normalize_action_name(action: dict) -> dict:
    if not isinstance(action, dict):
        return action
    name = action.get("action")
    if isinstance(name, str) and name in _ACTION_ALIASES:
        out = dict(action)
        out["action"] = _ACTION_ALIASES[name]
        return out
    return action


def _safe_research_context(table: dict, retrieve_fn: Any) -> dict:
    if retrieve_fn is None:
        return {}
    try:
        ctx = retrieve_fn(table)
        return ctx if isinstance(ctx, dict) else {}
    except Exception:
        return {}


def _emit_heartbeat(phase, completed, target, score, pending_count, label="", eta_str=""):
    prefix = f"[arena-pokerkit{label}]"
    print(f"{prefix} phase={phase} | completedHands={completed}/{target} | "
          f"adjustedBbPer100={score} | pending={pending_count}{eta_str}")


def _compute_eta(start_time, hands_done, target):
    try:
        hd = int(hands_done or 0)
        tgt = int(target or 0)
    except (TypeError, ValueError):
        return ""
    if hd <= 0 or tgt <= 0 or tgt <= hd:
        return ""
    elapsed = time.monotonic() - start_time
    if elapsed <= 0:
        return ""
    remaining = tgt - hd
    eta_s = int(remaining * (elapsed / hd))
    return f" | ETA {eta_s // 60}m{eta_s % 60:02d}s"


def _attempt_credential_repair(client, args):
    try:
        from arena_client import _move_creds_aside, _restore_creds_backup
        _move_creds_aside()
        client.api_key = None
        try:
            from arena_client import load_or_register
            creds = load_or_register(client, args.handle, args.name, args.quote)
        except Exception:
            _restore_creds_backup()
            raise
        return bool(creds.get("apiKey") or client.api_key)
    except Exception:
        return False


def _run_benchmark_loop(
    client,
    args,
    competition_id,
    decide_fn,
    retrieve_fn,
    terminal_phases,
    terminal_statuses,
    label="",
):
    """Shared benchmark loop used by both live and dry-run paths."""
    state = load_state()
    rng = _random.Random()
    last_completed_hands = 0
    saw_status_refresh = False
    last_status_at = 0.0
    last_heartbeat_at = 0.0
    credential_repair_used = False
    loop_start_monotonic = time.monotonic()

    _emit_heartbeat(phase="(starting)", completed=0, target="?", score=None,
                    pending_count=0, label=label, eta_str="")
    last_heartbeat_at = time.time()

    while True:
        tables = []
        try:
            pending = client.get(
                f"/texas/pending-actions?competitionId={competition_id}")
            tables = _validate_pending_tables(pending)
            tables = sorted(tables, key=lambda t: (t.get("actionDeadlineAt") or 0))
        except ArenaError as e:
            print(f"[arena-pokerkit] pending-actions error: {e}", file=sys.stderr)
            if e.status in (401, 403):
                if not credential_repair_used and _attempt_credential_repair(client, args):
                    credential_repair_used = True
                    continue
                return 4
            if e.status == 404:
                raise

        if tables:
            table = tables[0]
            deadline_ms = table.get("actionDeadlineAt") or 0
            deadline_s = (max(0.0, (deadline_ms / 1000.0) - time.time())
                          if deadline_ms else 10.0)
            research_context = _safe_research_context(table, retrieve_fn)
            try:
                action = decide_fn(table, deadline_s=deadline_s,
                                   research_context=research_context)
            except TypeError:
                action = decide_fn(table, deadline_s=deadline_s)
            action = _normalize_action_name(action)
            payload = {"tableId": table["tableId"], **action}
            try:
                client.post("/texas/action", payload)
                state["hands_played"] = state.get("hands_played", 0) + 1
                state["last_action"] = {
                    "action": action["action"],
                    "amount": action.get("amount"),
                    "at": int(time.time()),
                }
                save_state(state)
            except ArenaError as e:
                if e.status == 409:
                    state["stale_count"] = state.get("stale_count", 0) + 1
                    save_state(state)
                    continue
                if e.status in (401, 403):
                    if not credential_repair_used and _attempt_credential_repair(client, args):
                        credential_repair_used = True
                        continue
                    return 4
                if e.status == 400:
                    state["rejection_count"] = state.get("rejection_count", 0) + 1
                    save_state(state)
                    try:
                        client.post("/texas/action", {
                            "tableId": table["tableId"],
                            "action": "fold",
                            "message": "fallback after illegal action",
                            "reasoning": FALLBACK_REASONING,
                        })
                    except ArenaError:
                        pass
                    continue
                raise
            if (args.max_hands and saw_status_refresh
                    and last_completed_hands >= args.max_hands):
                print(f"[arena-pokerkit] hit --max-hands={args.max_hands} "
                      f"(completedHands={last_completed_hands}), stopping")
                return 0

        now = time.time()
        if (not tables) or (now - last_status_at >= STATUS_REFRESH_S):
            status = None
            try:
                status = client.get(
                    f"/texas/benchmark/status?competitionId={competition_id}")
            except ArenaError as e:
                print(f"[arena-pokerkit] status refresh error: {e}", file=sys.stderr)
                if e.status in (401, 403):
                    if not credential_repair_used and _attempt_credential_repair(client, args):
                        credential_repair_used = True
                        continue
                    return 4
            last_status_at = now
            if isinstance(status, dict):
                match = status.get("match") or {}
                saw_status_refresh = True
                try:
                    last_completed_hands = int(match.get("completedHands") or 0)
                except (TypeError, ValueError):
                    last_completed_hands = 0
                if (args.max_hands and last_completed_hands >= args.max_hands):
                    return 0
                if now - last_heartbeat_at >= 5.0:
                    eta_str = _compute_eta(loop_start_monotonic,
                                           match.get("completedHands"),
                                           match.get("targetHands"))
                    _emit_heartbeat(phase=match.get("phase"),
                                    completed=match.get("completedHands"),
                                    target=match.get("targetHands"),
                                    score=match.get("adjustedBbPer100"),
                                    pending_count=len(tables),
                                    label=label, eta_str=eta_str)
                    last_heartbeat_at = now
                phase = match.get("phase")
                msstatus = match.get("status")
                if phase in terminal_phases or msstatus in terminal_statuses:
                    print(f"[arena-pokerkit{label}] match terminal ({phase}/{msstatus}) | "
                          f"hands={match.get('completedHands')} | "
                          f"adjustedBbPer100={match.get('adjustedBbPer100')}")
                    return 0

        if not tables:
            time.sleep(POLL_INTERVAL + rng.uniform(-POLL_JITTER, POLL_JITTER))
