# Arena Gap Analysis

**Analyzed protocol:** https://arena.dev.fun/skills/arena.md  
**Project:** poker-agent (Texas Hold'em decision agent)  
**Date:** 2026-05-30

---

## 1. Arena Protocol Summary

### Registration Process

1. **Check for existing credentials** — load `.arena-credentials`, validate via `GET /api/arena/agent/me`
2. **Identity proposal** — agent proposes name/bio based on personality; owner confirms
3. **Handle derivation** — `name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '').slice(0, 30)`, with random suffix on conflict (max 3 retries)
4. **Registration** — `POST /api/arena/auth/register` with `{handle, name, quote}`, returns `apiKey` + `agentId`
5. **Credential persistence** — immediately write to `.arena-credentials`

### Authentication

- Header: `x-arena-api-key: arena_sk_...`
- API keys begin with `arena_sk_`, 70+ characters, NOT recoverable
- Claims: `GET /api/arena/auth/claim/status` (links agent to X account for rewards)

### Submission Process (Prediction Competitions)

- Poll `GET /api/arena/challenge/current?competitionId=X` every ~60s
- Two game types: **PumpfunGraduationPrediction** (`submit-graduation`), **PumpfunPumpOrDumpPrediction** (`submit-pump-or-dump`)
- Submissions include prediction, confidence, decisionLog, signals, toolCalls

### Runtime Requirements

- Continuous operation via screen/tmux/nohup
- Polling loops: challenges (~60s), claim status (~5min), leaderboard
- Credential persistence to `.arena-credentials`

### Agent Interface (Poker-specific, via pokerkit)

- `decide(table, deadline_s) → {action, amount, reasoning}` — called per decision
- `retrieve_solver_context() → dict` — Auto Research hook
- `on_session_end(stats) → None` — post-session analytics

---

## 2. Already Satisfied Requirements

### Poker Arena Integration

| Requirement | Status | Location |
|------------|--------|----------|
| `decide()` function | Done | `decide.py` → `src/agent/main_agent.py` |
| `retrieve_solver_context()` | Done | `src/agent/main_agent.py` |
| `on_session_end()` hook | Done | `src/agent/main_agent.py` |
| Arena HTTP client | Done | `arena_client.py` (1700+ lines, httpx, retry, introspection) |
| Credential caching | Done | `.arena-credentials` + `arena_client.py:_load_or_register()` |
| Mock/dry-run infrastructure | Done | `mock.py` (500+ lines, multiple scenarios) |
| Agent config | Done | `config/agent_config.json` |
| Quick start script | Done | `run.sh` (dry-run, arena, selfplay, analytics modes) |
| Opponent modeling persists | Done | VPIP/PFR tracking in `src/engine/opponent_model.py` |
| Decision timeout safety | Done | `decision_timeout_ms: 300` fallback in config |

### Strategy & Performance

| Requirement | Status | Notes |
|------------|--------|-------|
| BB/100 tracking | Done | Per-opponent, per-strategy, per-position |
| VPIP/PFR self-tracking | Done | In stress test `HandResult` |
| Multi-opponent testing | Done | 29 bot archetypes, 100K hands |
| Strategy evolution | Done | Continuous mixing with EMA smoothing |
| Analytics pipeline | Done | Leak detector, meta analyzer, optimizer |

---

## 3. Missing Requirements

### Critical: Prediction Competition Support

| Requirement | Status | Gap |
|------------|--------|-----|
| Challenge polling loop | **Missing** | No `GET /challenge/current?competitionId=X` implementation |
| Graduation prediction | **Missing** | No `POST /challenge/:id/submit-graduation` endpoint |
| Pump/Dump prediction | **Missing** | No `POST /challenge/:id/submit-pump-or-dump` endpoint |
| Prediction decision engine | **Missing** | Entire codebase is poker-specific; no token/market analysis |
| Market data signals | **Missing** | No Pumpfun data sources, no token analysis tools |
| Competition discovery | Partial | `arena_client.py` has introspection but no prediction comp logic |
| Leaderboard polling | Partial | Client exists but no automated polling loop |
| Inter-agent messaging | **Missing** | No `GET /agent/messages/inbox` implementation |

### Moderate: Poker Arena Gaps

| Requirement | Status | Gap |
|------------|--------|-----|
| `.env` file with real API key | **Missing** | `.env.example` referenced but doesn't exist |
| Real `.arena-credentials` | **Missing** | Current file has `dry_key_xxx` placeholder |
| `tests/` directory | **Missing** | `run.sh test` references tests that don't exist |
| Python venv | **Missing** | `venv/` not created, `pokerkit` not installed |
| `logs/` directory | **Missing** | Referenced by config but not created |
| Registration flow automation | Partial | `arena_client.py` has `_load_or_register()` but no handle derivation |
| Claim URL flow | **Missing** | No claim status polling or notification logic |
| Screen/tmux persistence | **Missing** | No continuous operation setup |

### Minor: Documentation & Polish

| Requirement | Status | Gap |
|------------|--------|-----|
| Handle derivation from name | **Missing** | Arena requires automatic handle generation |
| 429 retry with Retry-After | Done | In `arena_client.py` |
| Introspection validation | Done | `fetch_introspection()` + `assert_endpoints()` |
| Credential backup on re-register | Done | `.arena-credentials.rejected` mechanism |

---

## 4. Fundamental Architecture Mismatch

The Arena protocol (arena.md) describes **prediction competitions** (Pumpfun token graduation/pump-or-dump), while this project is a **poker Hold'em decision agent**. These are completely different domains:

| Aspect | This Project | Arena Prediction Protocol |
|--------|-------------|--------------------------|
| Decision type | Poker action (fold/check/call/bet/raise) | Market prediction (Graduate/Fade, Pump/Dump) |
| Input | Cards, table state, opponent model | Challenge metadata, market data, signals |
| Output | `{action, amount, reasoning}` | `{prediction, confidence, decisionLog, signals}` |
| Strategy | Heuristic + Monte Carlo equity | Market analysis + signal processing |
| Dependencies | treys (hand eval), equity calc | Data sources (Pumpfun API, market data) |
| Core engine | `decision_engine.py` (poker) | Would need `prediction_engine.py` (markets) |
| Testing | Poker stress test (29 bots, 100K hands) | Historical challenge accuracy |

---

## 5. Required Code Changes

### If targeting Poker Arena (pokerkit):

```
Priority 1 — Get operational:
  [ ] Create .env with ARENA_API_KEY
  [ ] Run registration to get real .arena-credentials
  [ ] Install pokerkit + dependencies in venv
  [ ] Create tests/ directory with referenced test files
  [ ] Create logs/ directory

Priority 2 — Hardening:
  [ ] Add handle derivation logic to arena_client.py
  [ ] Add claim URL notification flow
  [ ] Verify decide() output matches Arena's expected format
  [ ] Verify strategy_weights/strategy_votes in output don't break Arena parser
  [ ] Add screen/tmux deployment script
  [ ] Test dry-run → mock → live pipeline end-to-end
```

### If targeting Prediction Competitions:

```
Priority 1 — New capability:
  [ ] Create src/prediction/ directory
  [ ] Implement prediction_engine.py (market analysis, signal processing)
  [ ] Implement challenge_poller.py (GET /challenge/current loop)
  [ ] Implement submission_client.py (POST submit-graduation, submit-pump-or-dump)
  [ ] Implement leaderboard_poller.py
  [ ] Add Pumpfun data source integration
  [ ] Create signal extraction from on-chain/market data

Priority 2 — Integration:
  [ ] Wire into existing arena_client.py auth flow
  [ ] Create decide_prediction() alongside decide()
  [ ] Add prediction competition mode to run.sh
  [ ] Test against mock prediction challenges
```

---

## 6. Summary

| Category | Count |
|----------|-------|
| Already satisfied (Poker Arena) | 12 |
| Missing — Prediction support | 8 |
| Missing — Poker Arena gaps | 7 |
| Missing — Documentation/polish | 4 |

**Verdict:** The project is ~60% Arena-ready for poker competitions. The core `decide()` interface, HTTP client, credential management, and mock infrastructure exist. Gaps are primarily operational (no real credentials, no venv, missing tests) rather than architectural.

For prediction competitions, the gap is fundamental — an entirely new decision pipeline would be needed. The existing poker strategy system (limp_value, raise_exploit, hybrid blending) has zero applicability to token prediction challenges.
