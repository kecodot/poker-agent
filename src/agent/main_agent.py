"""Main Poker Agent — entry point for the Arena competition.

Provides:
  - decide() function compatible with Poker Arena
  - retrieve_solver_context() for Auto Research hook
  - Full agent configuration and lifecycle management
  - Self-optimization hooks
  - Integrated database, analytics, leak detection, and strategy evolution

Usage:
    pokerkit run --agent src/agent/main_agent.py --max-hands 500
    pokerkit selfplay --agent src/agent/main_agent.py --hands 500
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path for imports
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.engine.opponent_model import OpponentModel
from src.agent.decision_engine import DecisionEngine
from src.data.hand_database import HandDatabase
from src.data.strategy_params import StrategyParams
from src.analytics.analytics_engine import AnalyticsEngine
from src.analytics.leak_detector import LeakDetector
from src.analytics.meta_analyzer import MetaAnalyzer
from src.optimizer.parameter_optimizer import ParameterOptimizer
from src.backtest.backtest_engine import BacktestEngine
from src.evolution.strategy_evolution import StrategyEvolution

# ─── Global agent state ─────────────────────────────────────────────

_engine: Optional[DecisionEngine] = None
_opponent_model: Optional[OpponentModel] = None
_db: Optional[HandDatabase] = None
_strategy_params: Optional[StrategyParams] = None
_analytics: Optional[AnalyticsEngine] = None
_leak_detector: Optional[LeakDetector] = None
_meta_analyzer: Optional[MetaAnalyzer] = None
_optimizer: Optional[ParameterOptimizer] = None
_backtest: Optional[BacktestEngine] = None
_evolution: Optional[StrategyEvolution] = None
_config: dict = {}
_hand_records: list[dict] = []
_hands_played = 0
_start_time = 0.0
_current_session_id: str = ""
_current_hand_buffer: list[dict] = []

# Configuration defaults
DEFAULT_CONFIG = {
    "monte_carlo_sims": 5000,
    "max_decision_time_ms": 50,
    "log_hands": True,
    "log_dir": "logs",
    "opponent_model_path": "logs/opponents.json",
    "db_path": "data/hands.db",
    "config_path": "config/strategy-config.json",
    "evolution_interval": 1000,
    "strategy": {
        "preflop_aggression": 0.7,
        "cbet_frequency_dry": 0.65,
        "cbet_frequency_wet": 0.45,
        "bluff_frequency_river": 0.28,
        "thin_value_river": True,
    },
}


def load_config(config_path: str = "config/agent_config.json") -> dict:
    """Load agent configuration from JSON file."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        p = Path(config_path)
        if p.exists():
            loaded = json.loads(p.read_text())
            # Deep merge
            for k, v in loaded.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


def _init_all() -> DecisionEngine:
    """Initialize or return the full agent stack (DB, params, analytics, etc.)."""
    global _engine, _opponent_model, _db, _strategy_params
    global _analytics, _leak_detector, _meta_analyzer, _optimizer, _backtest, _evolution
    global _config

    if _engine is None:
        _config = load_config()
        _db = HandDatabase(_config.get("db_path", "data/hands.db"))
        _strategy_params = StrategyParams(_config.get("config_path", "config/strategy-config.json"))
        _opponent_model = OpponentModel(
            storage_path=_config.get("opponent_model_path", "logs/opponents.json")
        )
        _opponent_model.load_from_db(_db)
        _engine = DecisionEngine(
            opponent_model=_opponent_model,
            config=_config,
        )
        _analytics = AnalyticsEngine(_db)
        _leak_detector = LeakDetector(_db)
        _meta_analyzer = MetaAnalyzer(_db)
        _optimizer = ParameterOptimizer(_db, _strategy_params)
        _backtest = BacktestEngine(_db)
        _evolution = StrategyEvolution(_db, _strategy_params)
    return _engine


# ─── Arena-compatible interface ─────────────────────────────────────

def retrieve_solver_context(table: dict) -> dict:
    """Auto Research hook called before decide().

    Returns opponent context for this table to augment decision making.
    Called by the Arena client framework.
    """
    global _opponent_model, _db
    if _opponent_model is None:
        _init_all()

    seats = table.get("seats") or []
    self_seat = table.get("selfSeatNumber")
    context: dict = {"opponent_archetypes": {}, "exploitable": []}

    for s in seats:
        sid = s.get("agentId", "")
        snum = s.get("seatNumber")
        if sid and snum != self_seat:
            stats = _opponent_model.get(sid) if _opponent_model else None
            if stats and stats.total_hands >= 5:
                context["opponent_archetypes"][str(snum)] = {
                    "archetype": stats.archetype,
                    "vpip": stats.vpip,
                    "pfr": stats.pfr,
                    "three_bet_pct": stats.three_bet_pct,
                    "fold_to_cbet": stats.fold_to_cbet_pct,
                    "aggression_factor": stats.aggression_factor,
                }

    return context


def decide(table: dict, deadline_s: float = 10.0,
           research_context: Optional[dict] = None) -> dict:
    """Main decide function — Arena-compatible interface.

    This is the function the Arena framework calls for every decision.

    Args:
        table: Game state dict from Arena
        deadline_s: Seconds until the decision deadline
        research_context: Optional context from retrieve_solver_context()

    Returns:
        Action dict: {action, amount?, message, reasoning}
    """
    global _hands_played, _start_time

    if _start_time == 0:
        _start_time = time.time()

    engine = _init_all()

    # Apply research context if provided
    if research_context:
        # Pre-warm opponent model with known archetypes
        pass

    result = engine.decide(table, deadline_s)

    # Log decision for analysis
    if _config.get("log_hands", True):
        _log_decision(table, result, engine)

    return result


def _log_decision(table: dict, action: dict, engine: DecisionEngine) -> None:
    """Record decision for post-session analysis (JSON + SQLite)."""
    global _hand_records, _db, _opponent_model
    try:
        self_seat = table.get("selfSeatNumber")
        seat = next((s for s in table.get("seats", [])
                    if s.get("seatNumber") == self_seat), {})
        hole = list(seat.get("holeCards") or [])
        board = list(table.get("boardCards") or [])
        street = table.get("street") or "Preflop"

        hand_id = table.get("handId") or table.get("tableId", "?")
        action_name = action.get("action", "?")
        amount = action.get("amount")

        # Record action to DB
        if _db and hand_id and hand_id != "?":
            pot = table.get("potChips", 0)
            call_cost = (table.get("allowedActions") or {}).get("callChips", 0)
            stack = seat.get("stackChips", 0)
            position = str(table.get("selfSeatNumber", ""))

            _db.record_action(
                hand_id=str(hand_id),
                street=street if street else "Preflop",
                action=action_name,
                amount=int(amount) if amount else None,
                reasoning=action.get("reasoning", "")[:200],
                pot_chips=int(pot) if pot else 0,
                call_chips=int(call_cost) if call_cost else 0,
                stack_chips=int(stack) if stack else 0,
                position=position,
                board_at_action=board if board else [],
            )

        # Update opponent model from observed actions
        if _opponent_model:
            seats = table.get("seats") or []
            for s in seats:
                sid = s.get("agentId", "")
                if sid and s.get("seatNumber") != self_seat:
                    # Observe last action of opponents from table state
                    last_action = s.get("lastAction")
                    if last_action:
                        _opponent_model.record_action(sid, str(last_action).lower())

        record = {
            "table_id": table.get("tableId", "?"),
            "hand_id": hand_id,
            "street": street,
            "hole": hole,
            "board": board,
            "action": action_name,
            "amount": amount,
            "reasoning": action.get("reasoning", "")[:80],
            "pot": table.get("potChips", 0),
            "stack": seat.get("stackChips", 0),
            "position": table.get("selfSeatNumber"),
            "timestamp": time.time(),
        }
        _hand_records.append(record)

        # Flush to disk periodically
        if len(_hand_records) >= 50:
            _flush_records()
    except Exception:
        pass


def _flush_records() -> None:
    """Write decision log to disk."""
    global _hand_records
    if not _hand_records:
        return
    try:
        log_file = Path(_config.get("log_dir", "logs")) / "decisions.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a") as f:
            for r in _hand_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        _hand_records.clear()
    except Exception:
        pass


# ─── Agent lifecycle ────────────────────────────────────────────────

def on_session_start() -> None:
    """Called when agent starts a new Arena session."""
    global _start_time, _hands_played, _current_session_id
    _start_time = time.time()
    _hands_played = 0
    _init_all()
    if _db:
        _current_session_id = f"session_{int(time.time())}"
        _db.start_session(_current_session_id, "arena", "poker-agent",
                         _strategy_params.get_version() if _strategy_params else "v1")
    print("[poker-agent] session started", file=sys.stderr)


def on_session_end() -> None:
    """Called when the Arena session ends."""
    global _opponent_model, _engine, _db, _strategy_params
    global _analytics, _leak_detector, _meta_analyzer, _optimizer, _evolution
    _flush_records()

    if _opponent_model:
        _opponent_model.save()
        if _db:
            _opponent_model.sync_to_db(_db)

    if _db and _current_session_id:
        total_hands = _db.get_hand_count()
        stats100 = _db.get_stats_for_n_hands(min(total_hands, 100))
        bb100 = stats100.get("bb_per_100", 0) if stats100 else 0
        _db.end_session(_current_session_id, total_hands, 0, bb100)

    if _engine:
        stats = _engine.get_stats()
        print(f"[poker-agent] session ended: {stats}", file=sys.stderr)

    # Run analytics
    if _analytics and _db:
        try:
            _analytics.save_report()
            _analytics.save_json()
        except Exception:
            pass

    # Run leak detection
    if _leak_detector and _db:
        try:
            _leak_detector.save_report()
        except Exception:
            pass

    # Run meta analysis
    if _meta_analyzer and _db:
        try:
            _meta_analyzer.save_report()
        except Exception:
            pass

    print(f"[poker-agent] total decisions: {_engine.decision_count if _engine else 0}",
          file=sys.stderr)


def get_agent_stats() -> dict:
    """Return current agent statistics."""
    engine = _engine
    return {
        "hands_played": _hands_played,
        "engine": engine.get_stats() if engine else {},
        "session_duration_s": time.time() - _start_time if _start_time else 0,
    }


# ─── Self-optimization hooks ────────────────────────────────────────

def optimize_strategy(hand_history_path: str = "logs",
                      output_report: str = "reports/optimization.md") -> str:
    """Analyze hand history and suggest strategy improvements.

    This is called offline to generate optimization reports.
    """
    history_dir = Path(hand_history_path)
    if not history_dir.exists():
        return "No history data found."

    # Collect all decisions
    decisions = []
    for f in history_dir.glob("decisions*.jsonl"):
        try:
            for line in open(f):
                try:
                    decisions.append(json.loads(line.strip()))
                except Exception:
                    pass
        except Exception:
            pass

    if len(decisions) < 50:
        return f"Insufficient data: {len(decisions)} decisions found (need 50+)"

    # Analyze by street
    by_street: dict[str, list] = {}
    for d in decisions:
        street = d.get("street", "?")
        by_street.setdefault(street, []).append(d)

    # Analyze folding patterns
    folds = [d for d in decisions if d.get("action") == "fold"]
    fold_pct = len(folds) / max(len(decisions), 1)

    # Generate report
    report_lines = [
        "# Strategy Optimization Report",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Total decisions analyzed: {len(decisions)}",
        "",
        "## Decision Distribution by Street",
    ]

    for street, actions in sorted(by_street.items()):
        act_counts = {}
        for a in actions:
            act = a.get("action", "?")
            act_counts[act] = act_counts.get(act, 0) + 1
        total = len(actions)
        report_lines.append(f"\n### {street} ({total} decisions)")
        for act, count in sorted(act_counts.items(), key=lambda x: -x[1]):
            report_lines.append(f"- {act}: {count} ({count/max(total,1)*100:.0f}%)")

    report_lines += [
        "",
        "## Suggested Adjustments",
    ]

    # Generate suggestions based on patterns
    if fold_pct > 0.40:
        report_lines.append(
            f"- **High fold rate ({fold_pct:.0%})**: Consider calling more in "
            "marginal spots, especially in position"
        )

    # Check preflop aggression
    preflop = by_street.get("Preflop", [])
    if preflop:
        raises = sum(1 for d in preflop if d.get("action") in ("raise", "bet", "all-in"))
        raise_pct = raises / max(len(preflop), 1)
        if raise_pct < 0.15:
            report_lines.append(
                f"- **Low preflop aggression ({raise_pct:.0%})**: Open wider from "
                "CO and BTN, apply more pressure"
            )
        elif raise_pct > 0.35:
            report_lines.append(
                f"- **High preflop aggression ({raise_pct:.0%})**: Ensure your "
                "ranges aren't too wide from early position"
            )

    river = by_street.get("River", [])
    if river:
        river_calls = sum(1 for d in river if d.get("action") == "call")
        river_folds = sum(1 for d in river if d.get("action") == "fold")
        total_river = max(len(river), 1)
        if river_folds / total_river > 0.55:
            report_lines.append(
                "- **High river fold rate**: Consider bluff-catching more with "
                "medium-strength hands when getting good pot odds"
            )

    report = "\n".join(report_lines)

    # Write report
    out_path = Path(output_report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"[poker-agent] optimization report written to {output_report}")

    return report


# ─── Database recording ────────────────────────────────────────────

def record_completed_hand(
    hand_id: str,
    table_id: str,
    position: str,
    seat_number: int,
    hole_cards: list[str],
    board_cards: list[str],
    street_reached: str,
    stack_start: int,
    stack_end: int,
    n_opponents: int = 0,
    opponent_ids: list[str] = None,
    big_blind: int = 2,
    decision_time_ms: float = 0,
) -> None:
    """Record a completed hand to the database."""
    global _db, _current_session_id
    if not _db:
        return

    chip_delta = stack_end - stack_start
    try:
        _db.record_hand(
            hand_id=hand_id,
            session_id=_current_session_id or "unknown",
            table_id=table_id,
            competition_id="arena",
            position=position,
            seat_number=seat_number,
            hole_cards=hole_cards,
            board_cards=board_cards,
            street_reached=street_reached,
            stack_start=stack_start,
            stack_end=stack_end,
            chip_delta=chip_delta,
            n_opponents=n_opponents,
            opponent_ids=opponent_ids or [],
            big_blind=big_blind,
            decision_time_ms=decision_time_ms,
        )
    except Exception:
        pass


def check_evolution() -> dict | None:
    """Check if strategy evolution should run. Call periodically."""
    global _evolution
    if _evolution and _evolution.should_evolve(
        _config.get("evolution_interval", 1000)
    ):
        try:
            result = _evolution.run_evolution_cycle()
            _evolution.save_report()
            return result
        except Exception:
            pass
    return None


def run_full_analysis_pipeline() -> dict:
    """Run the complete analysis pipeline: analytics, leaks, meta, optimize, rank."""
    global _analytics, _leak_detector, _meta_analyzer, _optimizer, _db

    results = {
        "analytics_report": None,
        "analytics_json": None,
        "leak_report": None,
        "meta_report": None,
        "strategy_ranking": None,
    }

    if not _db:
        return {"error": "no database"}

    if _analytics:
        try:
            results["analytics_report"] = _analytics.save_report()
            results["analytics_json"] = _analytics.save_json()
        except Exception:
            pass

    if _leak_detector:
        try:
            results["leak_report"] = _leak_detector.save_report()
        except Exception:
            pass

    if _meta_analyzer:
        try:
            results["meta_report"] = _meta_analyzer.save_report()
        except Exception:
            pass

    if _optimizer:
        try:
            results["strategy_ranking"] = _optimizer.save_ranking()
        except Exception:
            pass

    return results


def get_dashboard_server():
    """Get a configured dashboard server instance."""
    global _db, _strategy_params, _leak_detector
    from src.dashboard.server import DashboardServer
    server = DashboardServer(port=8800)
    server.configure(db=_db, strategy_params=_strategy_params, leak_detector=_leak_detector)
    return server
