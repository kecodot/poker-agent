## baseline_v1 — Single-Strategy Monte Carlo Equity Agent

**First deployable poker agent for the dev.fun Poker Arena.**

### Architecture
- Monte Carlo equity simulation (configurable iterations)
- Street-by-street decision: preflop → flop → turn → river
- Position-based preflop hand ranges
- SPR-aware bet sizing
- 45 hot-reloadable strategy parameters

### Key Modules
- `DecisionEngine`: main decision pipeline with deadline safety
- `EquityCalculator`: Monte Carlo equity evaluation
- `HandEvaluator`: hand strength classification (pair, draw, etc.)
- `RangeEngine`: position-based preflop ranges
- `HandDatabase`: SQLite hand history with per-street recording
- `AnalyticsEngine`: BB/100, ROI, VPIP, PFR analytics

### Performance
- BB/100: +152.61 (A/B baseline, 2,000 hands)
- VPIP: 78.0%, PFR: 1.7%
- BTN BB/100: +32.17

### Infrastructure
- ArenaClient: HTTP client with 429/5xx retry, credential caching
- Mock: dry-run pipeline for zero-network testing
- Config: hot-reloadable JSON config with 45 parameters
- Deployment: run.sh quick-start script