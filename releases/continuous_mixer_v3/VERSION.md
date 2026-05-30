# continuous_mixer_v3 — Release Snapshot

**Release ID:** `continuous_mixer_v3`  
**Git Tag:** `arena-mixer-v3`  
**Commit:** `d128e2f` (HEAD)  
**Date:** 2026-05-30  
**Status:** CURRENT (arena_rc1)

---

## Strategy Description

Production-ready continuous strategy mixing agent. Builds on the adaptive routing architecture from v2, with the continuous mixer as the primary blending mechanism. The StrategyMixer computes contextual weights for all three strategies (limp_value, raise_exploit, hybrid) on every decision, blends via weighted voting, and smooths with exponential moving average (alpha 0.15-0.60 depending on pool confidence and changes).

**What's different from v2:**
- Continuous mixing is the **primary** blending path (StrategyMixer), not the static router
- EMA smoothing prevents strategy oscillation between hands
- Full documentation (README.md) with architecture overview
- Validated against 29 opponent types (100K hands, 100% profitable)
- Arena integration tested and verified

**Strategy Blend Distribution (typical):**
- Hybrid: ~48% weight (balanced baseline)
- Limp-Value: ~31% weight (passive exploit overlay)
- Raise-Exploit: ~21% weight (aggressive pressure overlay)

---

## Configuration Snapshot

```json
{
  "STRATEGY_VERSION": "v1",
  "MC_SIMS_DEFAULT": 5000,
  "MAX_DECISION_TIME_MS": 50,
  "DEADLINE_SAFETY_MS": 1500,
  "ADJUST_TO_OPPONENT": true,
  "EXPLOIT_NITS": true,
  "EXPLOIT_MANIACS": true,
  "EXPLOIT_PASSIVE": true,
  "OPEN_SIZE_BTN": 2.0,
  "OPEN_SIZE_CO": 2.3,
  "CBET_DRY_SIZE": 0.33,
  "CBET_WET_SIZE": 0.66,
  "BLUFF_FACTOR": 0.28,
  "STEAL_FACTOR": 1.0,
  "PREFLOP_AGGRESSION": 0.7,
  "CBET_FREQUENCY_DRY": 0.65,
  "CBET_FREQUENCY_WET": 0.45
}
```

---

## Performance Metrics

| Metric | Value | Source |
|--------|-------|--------|
| BB/100 | **+176.78** | Robustness test (100K hands, 29 opponents) |
| Win Rate | 50.5% | Robustness test |
| VPIP | 57.4% | Robustness test |
| PFR | 3.5% | Robustness test |
| Net Chips | +353,539 | Robustness test |
| Decision Time | ~6.6ms avg | Arena live test |
| Arena Rejection Rate | 0% | Arena live test (seed_poker_eval_s1) |

**Per-Strategy Breakdown:**

| Strategy | Hands | BB/100 | Win Rate | Share |
|----------|-------|--------|----------|-------|
| Limp-Value (passive exploit) | 21,011 | **+240.11** | 59.6% | 42.0% |
| Hybrid (balanced) | 21,425 | +146.17 | 46.4% | 42.9% |
| Raise-Exploit (aggressive) | 7,558 | +64.45 | 25.5% | 15.1% |

**Top 5 Best Matchups:**

| Opponent | BB/100 | Pool |
|----------|--------|------|
| HyperAggroBot | +702.86 | Aggressive |
| BigPotBot | +418.59 | Aggressive |
| OverbetBot | +327.09 | Aggressive |
| RandomizedBot | +263.98 | Mixed |
| LAGBot | +250.91 | Aggressive |

**Top 5 Worst Matchups (all profitable):**

| Opponent | BB/100 | Pool |
|----------|--------|------|
| SmallBallBot | +77.61 | Passive |
| TAGBot | +190.76 | Mixed |
| MonteCarloBot | +176.60 | Mixed |
| NitBot | +127.38 | Passive |
| CallBot | +218.40 | Passive |

**Arena Live Test (seed_poker_eval_s1):**
- 16 hands played, 0 rejections, 0 stales, 0 timeouts
- BB/100: -15.63 (small sample, variance expected)

---

## Files

All files from v2 plus:
- `README.md` — architecture overview, performance summary, quick start guide
- `ARENA_CONNECTION_REPORT.md` — verified Arena integration (all 8 tests passed)
- Arena registration: agent `cmps4z55q0i87o3b28s04ilfj` (handle: `poker-agent`)
