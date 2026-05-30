# Release Index

Poker Agent release history. Each release is a complete strategy snapshot.

---

## Releases

| # | Release ID | Tag | Status | BB/100 | Key Innovation |
|---|-----------|-----|--------|--------|---------------|
| 3 | `continuous_mixer_v3` | `arena-mixer-v3` | **CURRENT (rc1)** | +176.78 | Continuous strategy blending with EMA smoothing |
| 2 | `adaptive_router_v2` | `arena-adaptive-v2` | Superseded | +176.78 | Multi-strategy pool classification + adaptive routing |
| 1 | `baseline_v1` | `arena-baseline-v1` | Superseded | +152.61 | Single-strategy Monte Carlo equity agent |

---

## Evolution Path

```
baseline_v1                    adaptive_router_v2               continuous_mixer_v3
(commit 4158d71)               (commit 8d069c7)                 (commit d128e2f, HEAD)
──────────────────────────────────────────────────────────────────────────────────────
Single strategy      ──►      3 strategies + pool       ──►    Continuous blending
Monte Carlo equity             classifier + router              EMA smoothing
No adaptation                  Opponent archetypes              Production ready
                               Strategy mixer                   29 opponents verified
```

---

## Quick Rollback

```bash
# Rollback to any prior release
python3 -c "
from releases.rollback import rollback_to_release
rollback_to_release('baseline_v1')  # or 'adaptive_router_v2'
"

# Or via git
git checkout arena-baseline-v1    # v1 code
git checkout arena-adaptive-v2    # v2 code
git checkout arena-mixer-v3       # v3 (current)
```

---

## Files

| Directory | Contents |
|-----------|----------|
| `baseline_v1/` | VERSION.md, config snapshot |
| `adaptive_router_v2/` | VERSION.md, config snapshot |
| `continuous_mixer_v3/` | VERSION.md, config snapshot |
| `rollback.py` | Automated rollback to any release |
