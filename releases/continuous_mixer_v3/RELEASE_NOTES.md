## continuous_mixer_v3 — Production-Ready Continuous Strategy Blending

**Release Candidate 1 (arena_rc1) for live Arena deployment.**

### What's New from v2
- Continuous mixing as primary blending path (replaces static routing)
- EMA smoothing (alpha 0.15-0.60) prevents strategy oscillation
- Full documentation: README with architecture + performance summary
- Arena live integration verified: all 8 tests passed, 0 rejections
- Agent registered: `cmps4z55q0i87o3b28s04ilfj` (handle: `poker-agent`)

### Arena Verification
- Competition: `seed_poker_eval_s1` (500 hands)
- All 6 poker endpoints reachable
- decide() returns valid actions in ~6.6ms
- Extra fields (strategy_weights, etc.) harmlessly ignored by Arena
- 0 rejections, 0 stales, 0 timeouts in benchmark loop

### Performance
- BB/100: +176.78 (100K hands, 29 opponents)
- Win Rate: 50.5%, VPIP: 57.4%, PFR: 3.5%
- All opponents profitable, all pools profitable

### Deployment
```bash
./run.sh dry-run        # Verify locally
./run.sh arena          # Deploy to Arena
python3 releases/rollback.py adaptive_router_v2  # Rollback if needed
```