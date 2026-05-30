# Poker Agent — Adaptive Texas Hold'em AI

A data-driven poker AI with continuous strategy blending, opponent modeling, and automated robustness testing. Built for the Poker Arena competition framework.

## Performance

| Metric | Value |
|--------|-------|
| BB/100 | **+176.8** |
| Win Rate | 50.5% |
| VPIP | 57.4% |
| PFR | 3.5% |

*100K hands across 29 opponent archetypes. Profitable against all types.*

## Architecture

```
src/
├── agent/          # Decision engine, main agent entry point
├── strategy/       # Strategy implementations and blending
│   ├── limp_value.py        # Passive exploit strategy
│   ├── hybrid.py            # Balanced GTO-approximation
│   ├── preflop.py           # Raise-exploit (aggressive)
│   ├── flop.py / turn.py / river.py
│   ├── strategy_mixer.py    # Continuous weighted blending
│   ├── strategy_router.py   # Opponent pool routing
│   └── pool_classifier.py   # Bot type → pool classification
├── engine/         # Hand evaluation, equity, opponent modeling
├── validation/     # Stress testing and robustness framework
│   ├── arena_stress_test.py         # 100K-hand local simulation
│   └── opponent_diversification.py  # 29 opponent archetypes
├── analytics/      # Position and leak analysis
├── evolution/      # Self-optimization hooks
├── optimizer/      # Strategy parameter optimization
├── training/       # Training pipeline
└── backtest/       # Historical hand analysis
```

## Strategy System

**Continuous Strategy Mixing** blends three specialized strategies based on opponent profiling:

| Strategy | Pool | Approach |
|----------|------|----------|
| Limp-Value | Passive | Trap aggressive opponents, extract max value |
| Raise-Exploit | Aggressive | Isolate and pressure weak ranges |
| Hybrid | Mixed | Balanced frequencies for unknown opponents |

Weights are dynamically adjusted by: pool type, hand strength, position, stack depth, street, pot-to-stack ratio, and table aggression. An exponential moving average smooths transitions with confidence-based alpha (0.15–0.60).

### Pool Performance

| Pool | BB/100 | Win Rate |
|------|--------|----------|
| Aggressive | +269.1 | 44.2% |
| Mixed | +140.1 | 50.0% |
| Passive | +107.8 | 60.5% |

## Opponent Diversification

29 opponent archetypes tested, covering the full behavioral taxonomy:

- **Nit variants**: UltraNitBot (5% VPIP)
- **LAG variants**: HyperAggroBot (95% VPIP), 3BetManiacBot (45% 3bet)
- **Trap variants**: TrapBot, CheckRaiseBot (40% x/r)
- **Sizing variants**: MinRaiseBot, OverbetBot (3x pot), SmallBallBot
- **Range variants**: PolarizedBot, FitOrFoldBot
- **GTO variants**: GTOApproxBot, ExploitBot
- **Money-pressure**: ShortStackBot, DeepStackBot, BigPotBot
- **Chaos**: RandomizedBot, StationBot, DonkBetBot

### Top 5 Best Matchups

| Opponent | BB/100 |
|----------|--------|
| HyperAggroBot | +702.9 |
| BigPotBot | +418.6 |
| OverbetBot | +327.1 |
| RandomizedBot | +264.0 |
| LAGBot | +250.9 |

## Quick Start

```bash
# Run standard stress test (7 opponents, 100K hands)
python3 -m src.validation.arena_stress_test --hands 100000

# Run A/B comparison (baseline vs optimized)
python3 -m src.validation.arena_stress_test --abtest --hands 50000

# Run robustness test (29 opponents, 100K hands)
python3 -m src.validation.arena_stress_test --robustness --hands 100000

# Run as Arena agent
pokerkit run --agent src/agent/main_agent.py --max-hands 500
```

## Key Metrics Tracked

- BB/100 per opponent type, pool archetype, and position
- Per-strategy EV breakdown (limp_value / raise_exploit / hybrid)
- VPIP / PFR / Win Rate / ROI
- Strategy weight distribution and blend history
- Variance (std dev) per opponent type

## Reports

- `reports/robustness_report.md` — Full danger ranking across all 29 opponents
- `reports/validation_report.md` — Standard stress test results
- `strategy_performance_report.json` — Per-strategy BB/100 and opponent-type EV
