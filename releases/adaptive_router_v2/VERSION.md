# adaptive_router_v2 — Release Snapshot

**Release ID:** `adaptive_router_v2`  
**Git Tag:** `arena-adaptive-v2`  
**Commit:** `8d069c7`  
**Date:** 2026-05-30  
**Status:** SUPERSEDED by continuous_mixer_v3

---

## Strategy Description

Multi-strategy agent with opponent pool classification and adaptive strategy selection. Introduces three complementary strategy modes and a StrategyRouter that selects the best mode per-hand based on opponent archetype classification.

**New in v2:**
- **Pool Classifier** (`pool_classifier.py`): Classifies opponent table as `passive`, `aggressive`, or `mixed` based on VPIP/PFR/aggression stats
- **Strategy Router** (`strategy_router.py`): Selects pure discrete strategy mode per-hand via `classify_and_select()` with per-position overrides (BTN must always be profitable)
- **Limp-Value Strategy** (`limp_value.py`): Passive exploit — trap aggressive opponents, extract max value
- **Hybrid Strategy** (`hybrid.py`): Balanced GTO-approximation for mixed/unknown pools
- **Strategy Mixer** (`strategy_mixer.py`): Continuous weighted blending (EMA-smoothed) — mixes all three strategies per decision via weighted voting
- **Opponent Diversification** (`opponent_diversification.py`): 29 opponent archetypes including 7 originals + 22 new types
- **Arena Stress Test** (`arena_stress_test.py`): Multi-opponent validation framework
- **Position Analyzer** (`position_analyzer.py`): Per-position profitability tracking

**Architecture Flow:**
1. Classify opponent pool → `passive` / `aggressive` / `mixed`
2. Compute contextual strategy weights via StrategyMixer
3. Run all three strategies, collect votes
4. Blend via weighted voting (EMA smoothing across hands)
5. Validate against allowed actions

---

## Configuration Snapshot

```json
{
  "STRATEGY_VERSION": "v1",
  "MC_SIMS_DEFAULT": 2000,
  "MC_SIMS_PRECISE": 5000,
  "ADJUST_TO_OPPONENT": true,
  "EXPLOIT_NITS": true,
  "EXPLOIT_MANIACS": true,
  "EXPLOIT_PASSIVE": true,
  "OPEN_SIZE_BTN": 2.0,
  "CBET_FACTOR": 1.0,
  "BLUFF_FACTOR": 1.0,
  "STEAL_FACTOR": 1.0,
  "CALL_DOWN_FACTOR": 1.0
}
```

---

## Performance Metrics

| Metric | Value | Source |
|--------|-------|--------|
| BB/100 | +176.78 | Robustness test (100K hands, 29 opponents) |
| Win Rate | 50.5% | Robustness test |
| VPIP | 57.4% | Robustness test |
| PFR | 3.5% | Robustness test |
| Net Chips | +353,539 | Robustness test (100K hands) |

**Per-Strategy Breakdown:**

| Strategy | Hands | BB/100 | Win Rate | Share |
|----------|-------|--------|----------|-------|
| Limp-Value | 21,011 | +240.11 | 59.6% | 42.0% |
| Hybrid | 21,425 | +146.17 | 46.4% | 42.9% |
| Raise-Exploit | 7,558 | +64.45 | 25.5% | 15.1% |

**Per-Pool Archetype:**

| Pool | BB/100 | Win Rate |
|------|--------|----------|
| Aggressive | +269.10 | 44.2% |
| Mixed | +140.12 | 50.0% |
| Passive | +107.75 | 60.5% |

**100% profitable against all 29 opponent types.** Worst matchup: SmallBallBot (+77.61 BB/100). Best matchup: HyperAggroBot (+702.86 BB/100).

---

## Files

**New in this version (13 files, +5,183 lines):**
- `src/strategy/strategy_mixer.py` — continuous weighted blending
- `src/strategy/strategy_router.py` — pool-based strategy selection
- `src/strategy/pool_classifier.py` — opponent archetype classification
- `src/strategy/limp_value.py` — passive exploit strategy
- `src/strategy/hybrid.py` — balanced GTO approximation
- `src/validation/arena_stress_test.py` — multi-opponent stress test
- `src/validation/opponent_diversification.py` — 29 bot archetypes
- `src/analytics/position_analyzer.py` — per-position tracking

**Modified from v1:**
- `src/agent/decision_engine.py` — integrated strategy blending
- `src/engine/range_engine.py` — improved position mapping
- `src/strategy/preflop.py` — pool-aware preflop aggression
- `src/strategy/flop.py` — pool-aware cbet logic
