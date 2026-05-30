# Arena Release Candidate

**Release Identifier:** `arena_rc1`  
**Strategy Version:** `continuous_mixer_v3`  
**Git Tag:** `arena-mixer-v3`  
**Commit:** `d128e2f`  
**Date:** 2026-05-30  

---

## Performance Summary

| Metric | Value |
|--------|-------|
| BB/100 | **+176.78** |
| Win Rate | 50.5% |
| VPIP | 57.4% |
| PFR | 3.5% |
| Net Chips (100K hands) | +353,539 |
| Opponents Profitable | **29 / 29 (100%)** |
| Worst Matchup | SmallBallBot (+77.61 BB/100) |
| Best Matchup | HyperAggroBot (+702.86 BB/100) |
| Arena 400 Rejection Rate | **0%** (verified live) |
| Decision Latency | ~6.6ms avg |

### Per-Pool Performance

| Pool Archetype | BB/100 | Win Rate |
|---------------|--------|----------|
| Aggressive | +269.10 | 44.2% |
| Mixed | +140.12 | 50.0% |
| Passive | +107.75 | 60.5% |

### Per-Strategy Blend

| Strategy | Weight | BB/100 (standalone) |
|----------|--------|---------------------|
| Limp-Value (passive exploit) | ~31% | +240.11 |
| Hybrid (balanced) | ~48% | +146.17 |
| Raise-Exploit (aggressive) | ~21% | +64.45 |

---

## Deployment Command

```bash
cd /root/poker-agent

# 1. Activate environment
source venv/bin/activate

# 2. Verify dry-run
./run.sh dry-run

# 3. Deploy to Arena (auto-registers if needed)
export ARENA_API_BASE=https://arena.dev.fun/api/arena
export ARENA_COMPETITION_ID=seed_poker_eval_s1
./run.sh arena

# 4. Monitor
tail -f logs/decisions.jsonl
```

---

## Rollback Command

```bash
# Rollback to adaptive_router_v2
python3 releases/rollback.py adaptive_router_v2

# Rollback to baseline_v1
python3 releases/rollback.py baseline_v1

# Return to current
python3 releases/rollback.py continuous_mixer_v3

# List available releases
python3 releases/rollback.py --list
```

---

## Arena Registration

| Field | Value |
|-------|-------|
| Agent ID | `cmps4z55q0i87o3b28s04ilfj` |
| Handle | `poker-agent` |
| API Key | Stored in `.arena-credentials` |
| Competition | `seed_poker_eval_s1` (500 hands) |
| Auth Verified | Yes (all 8 integration tests passed) |

---

## Release Notes

### What's Included

- **Continuous Strategy Mixer**: All three strategies blended via EMA-smoothed weighted voting every decision
- **Opponent Pool Classification**: Passive / Aggressive / Mixed detection
- **29 Opponent Archetypes**: Comprehensive coverage including edge cases
- **100K-Hand Validation**: 100% profitable across all opponent types
- **Arena Live Verification**: 0 rejections, 0 stales, 0 timeouts
- **Rollback System**: Instant rollback to any prior release

### What's NOT Included

- Neural network / RL models (by design — pure strategy engine)
- Prediction competition support (Pumpfun — out of scope)
- Multi-table support (single table per benchmark)
- X claim URL completion (not required for competition)

### Known Limitations

- PFR is low (3.5%) — agent is passive preflop, preferring to see flops and exploit postflop
- BTN profitability not yet measured in robustness framework
- Small sample in live Arena (16 hands, variance noise)

---

## File Manifest

```
releases/
  INDEX.md                          — Release index and quick reference
  release_comparison.md             — Cross-version performance comparison
  rollback.py                       — Automated rollback tool
  baseline_v1/
    VERSION.md                      — Version description and metrics
    RELEASE_NOTES.md                — Detailed release notes
    strategy-config.json            — Config snapshot
    agent_config.json               — Agent config snapshot
  adaptive_router_v2/
    VERSION.md
    RELEASE_NOTES.md
    strategy-config.json
    agent_config.json
  continuous_mixer_v3/
    VERSION.md
    RELEASE_NOTES.md
    strategy-config.json
    agent_config.json
```
