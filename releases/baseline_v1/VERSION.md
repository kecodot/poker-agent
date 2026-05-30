# baseline_v1 — Release Snapshot

**Release ID:** `baseline_v1`  
**Git Tag:** `arena-baseline-v1`  
**Commit:** `4158d71`  
**Date:** 2026-05-30  
**Status:** SUPERSEDED by adaptive_router_v2

---

## Strategy Description

Single-strategy Texas Hold'em agent with Monte Carlo equity evaluation and basic board texture analysis. Street-by-street decision making (preflop/flop/turn/river) with SPR awareness. No opponent modeling, no strategy blending, no adaptation.

**Architecture:**
- Single decision path: equity calculation → pot odds → action threshold
- Monte Carlo equity simulation (configurable iterations)
- Position-based preflop hand ranges
- Basic cbet/bluff frequencies on flop/turn/river

**Key Limitation:** No opponent adaptation. Static strategy regardless of opponent type.

---

## Configuration Snapshot

```json
{
  "STRATEGY_VERSION": "v1",
  "MC_SIMS_DEFAULT": 2000,
  "OPEN_SIZE_BTN": 2.0,
  "OPEN_SIZE_CO": 2.3,
  "OPEN_SIZE_MP": 2.5,
  "OPEN_SIZE_UTG": 2.5,
  "CBET_FACTOR": 1.0,
  "BLUFF_FACTOR": 1.0,
  "ADJUST_TO_OPPONENT": false,
  "EXPLOIT_NITS": false,
  "EXPLOIT_MANIACS": false,
  "EXPLOIT_PASSIVE": false
}
```

---

## Performance Metrics

| Metric | Value | Source |
|--------|-------|--------|
| BB/100 | +152.61 | A/B baseline (2,000 hands vs bot pool) |
| VPIP | 78.0% | A/B baseline |
| PFR | 1.7% | A/B baseline |
| Win Rate | 52.5% | A/B baseline |
| BTN BB/100 | +32.17 | A/B baseline |
| ROI | 1.53% | A/B baseline |

---

## Files

Key source files at this version:
- `src/agent/decision_engine.py` — single-strategy decision engine
- `src/engine/equity_calculator.py` — Monte Carlo equity
- `src/engine/hand_evaluator.py` — hand strength classification
- `src/engine/range_engine.py` — position-based ranges
- `src/strategy/preflop.py` — preflop strategy
- `src/strategy/flop.py` — flop strategy
- `src/strategy/turn.py` — turn strategy
- `src/strategy/river.py` — river strategy
- `config/strategy-config.json` — 45 hot-reloadable parameters
- `config/agent_config.json` — agent runtime config

**NOT present in this version:**
- `src/strategy/strategy_mixer.py`
- `src/strategy/strategy_router.py`
- `src/strategy/pool_classifier.py`
- `src/strategy/limp_value.py`
- `src/strategy/hybrid.py`
- `src/validation/opponent_diversification.py`
- `src/validation/arena_stress_test.py`
