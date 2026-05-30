#!/bin/bash
# Poker Agent — Quick Start Script
# Usage:
#   ./run.sh test          Run unit tests
#   ./run.sh selfplay      Run local self-play (200 hands)
#   ./run.sh dry-run       Dry-run against mock Arena
#   ./run.sh arena         Live 500-hand Arena match
#   ./run.sh analytics     Generate analytics reports (BB/100, VPIP, etc.)
#   ./run.sh leaks         Run leak detector → leak_report.json
#   ./run.sh meta          Run meta analyzer → meta-report.md
#   ./run.sh optimize      Run parameter optimizer → strategy-ranking.json
#   ./run.sh backtest      Run backtest comparison
#   ./run.sh dashboard     Start monitoring dashboard on port 8800
#   ./run.sh full-analysis Run complete analysis pipeline
#   ./run.sh shell         Enter virtual environment

set -e
cd "$(dirname "$0")"

# Setup venv if needed
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install httpx python-dotenv treys
else
    source venv/bin/activate
fi

case "${1:-help}" in
    test)
        echo "=== Running Unit Tests ==="
        python tests/test_hand_evaluator.py
        python tests/test_range_engine.py
        python tests/test_equity_calculator.py
        python tests/test_decision_engine.py
        echo "=== All Tests Passed ==="
        ;;
    selfplay)
        HANDS="${2:-200}"
        echo "=== Self-Play: $HANDS hands ==="
        python -c "
from src.training.self_play import SelfPlayRunner
from decide import decide
runner = SelfPlayRunner(decide)
stats = runner.run_session(n_hands=$HANDS, opponent_type='mixed')
print()
print('─' * 56)
for k, v in stats.items():
    if k != 'by_position':
        print(f'  {k}: {v}')
print('─' * 56)
"
        ;;
    dry-run)
        echo "=== Dry Run ==="
        python -c "
from mock import run_mock_benchmark
import argparse
from decide import decide
args = argparse.Namespace(
    dry_run=True, dry_run_scenario='instant', max_hands=10,
    competition_id='comp_dryrun', agent=None,
    handle='poker-agent', name='Poker Agent', quote='probability over swagger'
)
rc = run_mock_benchmark(args, decide_fn=decide)
print(f'Dry-run exit code: {rc}')
"
        ;;
    arena)
        HANDS="${2:-500}"
        echo "=== Arena Match: $HANDS hands ==="
        echo "Make sure .env is configured with ARENA_API_KEY"
        python -c "
import os, sys
from dotenv import load_dotenv
load_dotenv()
if not os.environ.get('ARENA_API_KEY'):
    print('ERROR: ARENA_API_KEY not set in .env')
    print('Get your API key from https://arena.dev.fun')
    sys.exit(1)
from arena_client import ArenaClient, DEFAULT_BASE, load_or_register
from examples.agent import _run_benchmark_loop, load_external_decide
import argparse
args = argparse.Namespace(
    competition_id=os.environ.get('ARENA_COMPETITION_ID', 'seed_poker_eval_s1'),
    dry_run=False, max_hands=$HANDS, agent=None,
    handle='poker-agent', name='Poker Agent', quote='probability over swagger'
)
decide_fn = decide
client = ArenaClient(os.environ.get('ARENA_API_BASE', DEFAULT_BASE),
                     api_key=os.environ.get('ARENA_API_KEY'))
try:
    creds = load_or_register(client, args.handle, args.name, args.quote)
    print(f'Agent: {creds.get(\"agentId\", \"?\")}')
    from arena_client import fetch_introspection, assert_endpoints, resolve_terminal_phases
    schema = fetch_introspection(client)
    assert_endpoints(schema)
    tp, ts = resolve_terminal_phases(schema)
    start = client.post('/texas/benchmark/start', {'competitionId': args.competition_id})
    print(f'Benchmark started: {start.get(\"match\", {}).get(\"phase\", \"?\")}')
    rc = _run_benchmark_loop(client, args, args.competition_id, decide_fn,
                             lambda t: {}, tp, ts, '')
    print(f'Match complete. Exit code: {rc}')
finally:
    client.close()
" 2>&1 || echo "Arena connection may need different setup. See deploy.md"
        ;;

    # ─── Phase 2: Analytics & Optimization ───────────────────────

    analytics)
        echo "=== Poker Analytics Engine ==="
        python -c "
from src.agent.main_agent import _init_all, run_full_analysis_pipeline
_init_all()
result = run_full_analysis_pipeline()
print()
print('Reports generated:')
for k, v in result.items():
    if v: print(f'  {k}: {v}')
"
        ;;

    leaks)
        echo "=== Leak Detector ==="
        python -c "
from src.agent.main_agent import _init_all
_init_all()
from src.agent.main_agent import _leak_detector, _db
if _db and _leak_detector:
    report = _leak_detector.save_report()
    leaks = _leak_detector.detect_all()
    print()
    print(f'Severity: {leaks.get(\"severity\", \"?\")}')
    print(f'Leaks found: {len(leaks.get(\"leaks_found\", []))}')
    for l in leaks.get('leaks_found', []):
        print(f'  [{l.get(\"severity\",\"?\").upper()}] {l.get(\"type\",\"?\")}: {l.get(\"suggestion\",\"\")}')
    print(f'Report: {report}')
"
        ;;

    meta)
        echo "=== Arena Meta Analyzer ==="
        python -c "
from src.agent.main_agent import _init_all
_init_all()
from src.agent.main_agent import _meta_analyzer
if _meta_analyzer:
    path = _meta_analyzer.save_report()
    data = _meta_analyzer.analyze()
    insights = _meta_analyzer.generate_insights(data)
    print()
    for i, ins in enumerate(insights, 1):
        print(f'{i}. {ins}')
    print(f'Report: {path}')
"
        ;;

    optimize)
        echo "=== Parameter Optimizer ==="
        python -c "
from src.agent.main_agent import _init_all
_init_all()
from src.agent.main_agent import _optimizer
if _optimizer:
    path = _optimizer.save_ranking()
    result = _optimizer.optimize()
    print()
    current = result.get('baseline', {})
    print(f'Current: BB/100={current.get(\"bb_per_100\",0)}, Score={current.get(\"score\",0)}')
    top = result.get('top_variants', [])
    if top:
        best = top[0]
        print(f'Best: {best.get(\"version\",\"?\")} BB/100={best.get(\"estimated_bb_per_100\",0)} Score={best.get(\"score\",0)}')
    print(f'Ranking saved: {path}')
"
        ;;

    backtest)
        echo "=== Backtesting Framework ==="
        python -c "
from src.agent.main_agent import _init_all
_init_all()
from src.agent.main_agent import _strategy_params, _backtest
if _strategy_params and _backtest:
    old_cfg = _strategy_params.get_all()
    new_cfg = dict(old_cfg)
    new_cfg['CBET_FACTOR'] = round(old_cfg.get('CBET_FACTOR', 1.0) * 1.2, 2)
    new_cfg['BLUFF_FACTOR'] = round(old_cfg.get('BLUFF_FACTOR', 1.0) * 0.8, 2)
    report = _backtest.compare_versions(old_cfg, new_cfg)
    print()
    print(f'Old: {report.get(\"old_version\",\"?\")} BB/100={report.get(\"old_bb_per_100\",0)}')
    print(f'New: {report.get(\"new_version\",\"?\")} BB/100={report.get(\"estimated_new_bb_per_100\",0)}')
    print(f'Delta: {report.get(\"estimated_delta\",0):+.2f}')
    print(f'Recommendation: {report.get(\"recommendation\",\"?\")}')
    _backtest.save_backtest_report(old_cfg, new_cfg)
"
        ;;

    dashboard)
        echo "=== Starting Dashboard on http://0.0.0.0:8800 ==="
        python -c "
from src.agent.main_agent import _init_all
_init_all()
from src.agent.main_agent import _db, _strategy_params, _leak_detector
from src.dashboard.server import DashboardServer
server = DashboardServer(port=8800)
server.configure(db=_db, strategy_params=_strategy_params, leak_detector=_leak_detector)
print()
print('Dashboard running at http://0.0.0.0:8800')
print('Open in browser to see real-time stats')
print('Press Ctrl+C to stop')
server.start(background=False)
"
        ;;

    full-analysis)
        echo "=== Full Analysis Pipeline ==="
        echo "Running: analytics + leaks + meta + optimize + backtest"
        echo ""
        bash "$0" analytics
        echo ""
        bash "$0" leaks
        echo ""
        bash "$0" meta
        echo ""
        bash "$0" optimize
        echo ""
        bash "$0" backtest
        echo ""
        echo "=== Full Analysis Complete ==="
        echo "Reports saved to reports/"
        ls -la reports/
        ;;

    shell)
        echo "Entering venv shell..."
        exec bash
        ;;

    *)
        echo "Poker Agent — Usage:"
        echo "  ./run.sh test          Run unit tests"
        echo "  ./run.sh selfplay      Local self-play (200 hands)"
        echo "  ./run.sh dry-run       Dry-run against mock"
        echo "  ./run.sh arena         Live 500-hand Arena match"
        echo "  ./run.sh analytics     Generate analytics reports"
        echo "  ./run.sh leaks         Run leak detector"
        echo "  ./run.sh meta          Run meta analyzer"
        echo "  ./run.sh optimize      Run parameter optimizer"
        echo "  ./run.sh backtest      Run backtest comparison"
        echo "  ./run.sh dashboard     Start monitoring dashboard (port 8800)"
        echo "  ./run.sh full-analysis Run complete analysis pipeline"
        echo "  ./run.sh shell         Enter venv"
        ;;
esac
