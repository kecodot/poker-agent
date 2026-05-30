# Poker Agent — Deployment Guide

## Quick Start

```bash
cd /root/poker-agent
./run.sh test       # Verify everything works
./run.sh selfplay   # Local self-play test
```

## Project Structure

```
poker-agent/
├── decide.py                          # Top-level decide() for Arena --agent flag
├── arena_client.py                    # Arena HTTP client (from starter kit)
├── mock.py                            # Dry-run mock infrastructure
├── run.sh                             # Quick start script
├── requirements.txt                   # Python dependencies
├── deploy.md                          # This file
├── config/
│   └── agent_config.json              # Agent configuration
├── src/
│   ├── engine/
│   │   ├── hand_evaluator.py          # Hand strength evaluation (treys)
│   │   ├── monte_carlo.py             # Multi-threaded Monte Carlo equity
│   │   ├── equity_calculator.py       # Pot odds / SPR / implied odds
│   │   ├── range_engine.py            # Position-based opening ranges
│   │   └── opponent_model.py          # VPIP/PFR/3BET tracking
│   ├── strategy/
│   │   ├── preflop.py                 # Preflop strategy
│   │   ├── flop.py                    # Flop strategy
│   │   ├── turn.py                    # Turn strategy
│   │   └── river.py                   # River strategy
│   ├── analytics/
│   │   ├── hand_history.py            # JSON hand history recording
│   │   └── opponent_stats.py          # Opponent analysis & reports
│   ├── agent/
│   │   ├── decision_engine.py         # Central decision pipeline
│   │   └── main_agent.py              # Agent lifecycle & optimization
│   └── training/
│       ├── self_play.py               # Local self-play runner
│       └── strategy_tuner.py          # Automated strategy optimization
├── tests/
│   ├── test_hand_evaluator.py
│   ├── test_range_engine.py
│   ├── test_equity_calculator.py
│   └── test_decision_engine.py
├── logs/                              # Hand history & opponent data
└── reports/                           # Optimization reports
```

## Installation

```bash
cd /root/poker-agent
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Connecting to Poker Arena

### Option A: Use with Starter Kit CLI

```bash
# Clone starter kit alongside this agent
cd /root
git clone https://github.com/devfun-org/poker-arena-starter-kit
cd poker-arena-starter-kit
cp .env.example .env
# Edit .env with your API key

# Install starter kit
uv sync

# Run our agent through the starter kit
./pokerkit run --agent /root/poker-agent/decide.py --max-hands 50
```

### Option B: Direct Python

```bash
cd /root/poker-agent
source venv/bin/activate
pip install .   # Install starter kit as a dependency

# Configure
cp .env.example .env  # Set ARENA_API_KEY

# Run
python -c "
from arena_client import ArenaClient
from decide import decide
# ... (see run.sh arena for full flow)
"
```

## Arena Integration

### Registration

The agent auto-registers on first run. Credentials are cached in `.arena-credentials`.

### Competition IDs

| Competition | ID | Hands | Duration |
|---|---|---|---|
| S1 (Poker Eval) | `seed_poker_eval_s1` | 500 | ~15 min |

### Environment Variables

```
ARENA_API_KEY=arena_sk_...
ARENA_API_BASE=https://arena.dev.fun/api/arena
ARENA_COMPETITION_ID=seed_poker_eval_s1
```

## Strategy Tuning

After every Arena session, run:

```bash
./run.sh tune
```

This analyzes the hand history and generates optimization suggestions in `reports/optimization.md`.

### Automated Tuning Pipeline

1. Run Arena match → hands recorded in `logs/decisions.jsonl`
2. Run `./run.sh tune` → generates `reports/optimization.md`
3. Apply suggested changes to `config/agent_config.json`
4. Re-run tests: `./run.sh test`
5. Re-run Arena to validate improvements

## Performance Benchmarks

| Metric | Target | Actual |
|---|---|---|
| Single decision | < 50ms | ~5ms (preflop), ~20ms (postflop MC) |
| Monte Carlo 5k sims | < 300ms | ~50-80ms (multi-threaded) |
| Memory | < 512MB | ~80MB baseline |

## Key Design Decisions

- **No LLM at runtime**: All decisions are deterministic heuristic + Monte Carlo. Fast, zero cost, fully inspectable.
- **Opponent modeling persists across sessions**: VPIP/PFR data saved to `logs/opponents.json`.
- **Strategy is config-driven**: All ranges and thresholds in `config/agent_config.json` for hot-reload.
- **Fallback-safe**: Every decision path has a deadline emergency fallback (check/fold).
- **Multi-threaded Monte Carlo**: Thread pool for parallel equity computation.

## Troubleshooting

### Monte Carlo too slow

Reduce `monte_carlo_sims` in `config/agent_config.json` from 5000 to 1000.

### Arena connection fails

1. Check `ARENA_API_KEY` in `.env`
2. Verify network: `curl https://arena.dev.fun/api/arena/__introspection`
3. Delete `.arena-credentials` and re-register

### Tests fail

```bash
source venv/bin/activate
pip install -r requirements.txt  # Ensure all deps are installed
python tests/test_hand_evaluator.py
```
