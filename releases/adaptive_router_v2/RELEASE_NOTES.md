## adaptive_router_v2 — Multi-Strategy Pool Classification + Adaptive Routing

**Three complementary strategies with opponent-aware selection.**

### What's New
- **Strategy Mixer**: Continuous weighted blending with EMA smoothing
- **Strategy Router**: Pool-aware discrete strategy selection
- **Pool Classifier**: Passive / Aggressive / Mixed opponent classification
- **Limp-Value Strategy**: Trap aggressive opponents, extract max value (+240 BB/100)
- **Hybrid Strategy**: Balanced GTO-approximation for unknown pools (+146 BB/100)
- **29 Opponent Archetypes**: 7 original + 22 diverse bot types
- **Position Analyzer**: Per-position profitability tracking

### Performance (100K hands, 29 opponents)
- BB/100: +176.78 — ALL 29 opponents profitable
- Per-pool: Aggressive +269, Mixed +140, Passive +108
- Per-strategy: Limp-Value +240, Hybrid +146, Raise-Exploit +64
- Best matchup: HyperAggroBot (+703 BB/100)
- Worst matchup: SmallBallBot (+78 BB/100)

### Files Changed
- 13 files, +5,183 lines
- 231 lines modified in existing strategy modules