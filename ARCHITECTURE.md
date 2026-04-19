# Architecture

Kiến trúc vnstock-bot — module, data flow, boundaries, schema. Để hiểu *bot
chạy như thế nào từng bước*, xem [OPERATIONS.md](OPERATIONS.md).

---

## Overview

Single Python process chạy trên event loop asyncio. 3 nguồn input chính
+ 1 scheduler song song:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  vnstock-bot (1 process, asyncio)                                        │
│                                                                          │
│  ┌──────────┐  ┌─────────────┐  ┌──────────┐  ┌────────────────────────┐│
│  │ Telegram │  │ APScheduler │  │MCP stdio │  │ CLI (doctor/backtest)  ││
│  │ long-poll│  │ cron        │  │ server   │  │                        ││
│  └────┬─────┘  └──────┬──────┘  └────┬─────┘  └──────────┬─────────────┘│
│       └────────┬──────┴──────────────┴────────────────────┘              │
│                ▼                                                         │
│         ┌────────────────────┐                                           │
│         │   Orchestrator     │   async DAG + 6 swarm preset             │
│         │   (run_preset)     │                                           │
│         └─┬────────────────┬─┘                                           │
│           │                │                                             │
│           ▼                ▼                                             │
│   single-agent        swarm DAG preset                                   │
│   (research.agent)    (bull/bear, review, macro, shadow…)                │
│                                                                          │
│  ┌──────┬─────────┬─────────┬────────┬────────┬────────┬────────┬──────┐│
│  │Tools │ Skills  │Validator│Memory  │Simulator│Bias    │Learning│Shadow││
│  │(MCP) │ 25+     │ chain   │ 5-layer│(ATO/T+2│7 detect│stats + │8-sect││
│  │      │         │+stat    │FTS5+L4 │+biên độ│        │FSM +   │HTML  ││
│  │      │         │ gate    │pattern │        │        │proposer│      ││
│  └──────┴─────────┴─────────┴────────┴────────┴────────┴────────┴──────┘│
│                                                                          │
│  Export (Pine v6) • Backtest (15 metrics + 4 optimizer)                  │
│                                                                          │
│  State:                                                                  │
│    • SQLite   data/bot.db   (operational)                                │
│    • Git      skills/  + strategy.md                                     │
│    • Files    data/memory/*.md   (5-layer persistent memory)             │
│    • Files    data/shadow/       (user CSV uploads)                      │
│    • Files    data/reports/      (HTML Delta-PnL reports)                │
│    • DuckDB   data/bot.duckdb    (read-only analytics — optional)        │
└──────────────────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
    Telegram API       vnstock (VCI/TCBS)     Claude Agent SDK
```

---

## Module layout

### `telegram/`
Telegram polling + handler. `bot.py` has v1-style commands (`/status`,
`/today`, …); `v2_handlers.py` adds the swarm/shadow/bias/recall/why/regime
commands + CSV upload document handler. Whitelisted chat IDs only.

### `scheduler/`
APScheduler cron jobs. `daily_research_job` is a dispatcher that picks
between `daily_research_single_job` (v1 single-agent) and
`daily_research_swarm_job` (orchestrator DAG) based on
`DAILY_RESEARCH_MODE`. `weekly_review_job` runs a 6-step pipeline
(score → stats compute → bias → lifecycle → patterns → skill proposer).

### `orchestrator/`
Async DAG runner + YAML preset loader. Nodes run in topological waves with
`asyncio.gather`. Each run gets a `trace_id` and a full audit trail in
`dag_traces` + `dag_node_results` (replay via `/why`).

Files: `dag.py` (runner), `nodes.py` (AgentRunner/FunctionRunner), `types.py`
(Pydantic specs), `preset_loader.py`, `streaming.py` (EventBus),
`builtins.py` (registered function handlers).

Presets in `config/swarm/*.yaml`:
| Preset | Nodes | Trigger |
|---|---|---|
| `quick_chat` | 1 agent | Every Telegram chat text |
| `daily_research` | snapshot → researcher → record_memory | Cron 15:30 (when mode=swarm) |
| `new_entry_debate` | bull ↔ bear (parallel) → risk_officer → PM | `/debate <ticker>` |
| `position_review` | 3 parallel checks → decider | `/review <ticker>` |
| `macro_sector_desk` | 3 parallel analysts → regime_labeler | Sunday weekly |
| `shadow_review` | parser → extractor → backtester → report | `/shadow upload` + CSV |

### `research/`
The only module that imports `claude_agent_sdk`. `agent.py` wraps
`ClaudeSDKClient` + builds an in-process MCP server from `tools.py`.
Buffered side effects (`_proposal_buffer`, `_skill_write_buffer`) are
flushed after the turn loop so the validator chain sees everything before
any persist.

### `skills/` (repo root, not under src)
25+ markdown files with YAML frontmatter. Categories:
- `analysis/` (8) — top-down-macro, sector-rotation, factor-research,
  valuation-model, multi-factor, fundamental-screen, catalyst-check,
  technical-trend
- `strategy/` (6) — candlestick (15 patterns), ichimoku, smc, momentum,
  breakout, mean-reversion
- `risk/` (5) — position-sizing, stop-loss-rules, correlation-check,
  drawdown-budget, regime-filter
- `flow/` (2) — foreign-flow, liquidity-check
- `tool/` (2) — backtest-diagnose, pine-script
- `playbooks/` (2) — new-entry, cut-loser

Frontmatter is authoritative for `status` (draft/shadow/active/archived),
`category`, `parent_skill`, `uses`, `win_rate_ci_95`, etc. CI fields are
populated by `learning/skill_stats_compute.py`, never hand-edited.

### `memory/`
5-layer memory:
- **L1 Events** — `events` table + `events_fts` (FTS5 unicode61 w/
  diacritic stripping + VN `đ` fold). Every tool call, chat turn, decision
  lands here.
- **L2 User prefs** — `data/memory/user_prefs/*.md` (markdown with YAML
  frontmatter).
- **L3 Summaries** — `summaries` table (daily/session rollups).
- **L4 Patterns** — `patterns` table. `patterns.py` extracts from winning
  decisions weekly; TTL 90d unless confirmed.
- **L5 Strategy** — `strategy.md` (hand + weekly-review written).

`recall.py` combines FTS5 hits + file hits into a single ranked result.
`compression.py` produces a budget-aware context string ordered L1→L5.

### `bias/`
Seven pure-function detectors. `types.py` → `TradeLike`/`DecisionLike`.
`detectors.py` → 7 detectors matching Vibe-Trading formulas
(disposition, overtrading, chase_momentum, anchoring, hot_hand,
skill_dogma, recency). `weekly_check.py` runs on bot's own decisions via
FIFO pairing + persists to `bias_reports`.

### `learning/`
- `scorer.py` — mark decisions as scored at 5/10/20d using invalidation.
- `skill_scorer.py` — v1 skill_scores aggregate (legacy, coexist).
- `skill_stats_compute.py` — bootstrap CI + walk-forward + MC perm per
  skill → UPSERT `skill_scores_v2`.
- `skill_lifecycle.py` — FSM `draft → shadow → active → archived` with
  stat gate; writes frontmatter + `skill_lifecycle_transitions` audit.
- `skill_proposer.py` — deterministic pattern → SkillDraft generator
  (reads L4 `patterns`).
- `stats.py` — numpy library: bootstrap, MC permutation, walk-forward.
- `weekly_review.py` — Claude agent for strategy.md + skill edits.

### `shadow/`
Broker CSV upload → rule extraction → Delta-PnL.
- `parsers/` — base + generic + SSI + VPS + TCBS (auto-detect).
- `pairing.py` — FIFO buy→sell roundtrips with fee apportioning.
- `rule_extractor.py` — cluster winners by (sector, hour_bucket,
  hold_bucket); emit ShadowRule with `human_text ≤ 30 chars`.
- `backtester.py` + `delta_pnl.py` — 5-component attribution
  (noise/early_exit/late_exit/overtrading/missed_signals).
- `report.py` — 8-section HTML with inline SVG equity curve.

### `portfolio/`
v1 core, still the simulator of record.
- `types.py` — Pydantic `DecisionInput`, dataclass `Holding`, `Portfolio`.
- `simulator.py` — ATO fill, T+2 settlement, fee bps, stop-loss checker.
- `validator.py` — Pydantic schema + business rules (biên độ, position
  cap 20% NAV, ≤10 vị thế, ≤2 mã/sector).
- `reporter.py` — markdown renderer.

### `backtest/`
- `runner.py` — deterministic momentum baseline replay (sanity check for
  the simulator).
- `metrics.py` — 15 performance metrics.
- `optimizers.py` — 4 portfolio optimizers (equal_weight, equal_volatility,
  risk_parity, max_diversification).
- `validation.py` — thin wrapper calling `learning/stats.py` (MC + boot +
  walk-forward) and emitting red flags.

### `export/`
Pine Script v6 generator. 5 templates: breakout, ma_cross, rsi_mr,
ichimoku, mf_screen.

### `mcp/`
Stdio JSON-RPC 2.0 server (MCP-compatible subset: initialize + tools/list
+ tools/call). Exposes 5 **read-only** tools (`get_price`,
`get_portfolio`, `search_memory`, `get_timeline`,
`recall_similar_decision`). CLI entry `vnstock-bot-mcp`.

### `data/`
`vnstock_client.py` wraps the vnstock package (VCI/TCBS). `watchlist.py`
loads `config/watchlist.yaml`. `holidays.py` has the VN trading calendar.
`cache.py` parquet dump per trading day. `market_snapshot.py` builds the
daily VN-Index + foreign flow snapshot.

### `db/`
Hand-managed SQLite. `schema.sql` is the source of truth (+ defensive
`_migrate_v2_columns` in `connection.py` for legacy DBs). `queries.py` is
the only module issuing raw SQL — everything else goes through typed
helpers.

### `config/`, `scripts`
- `watchlist.yaml` — seed tickers + sectors.
- `swarm/*.yaml` — 6 swarm preset.
- `pyproject.toml` `[project.scripts]` → `vnstock-bot` + `vnstock-bot-mcp`.

---

## Data flow — daily research

```
15:30 Asia/Ho_Chi_Minh (cron)
  │
  ├─ is_trading_day(today)? NO → heartbeat skip → exit
  │
  ├─ build_market_snapshot(today)              [data/market_snapshot]
  │    → VN-Index OHLC + foreign flow + top movers → market_snapshot row
  │
  ├─ release_t2_shares(today)                  [portfolio/simulator]
  │    → holdings.qty_available bumped for shares past T+2
  │
  ├─ fill_pending_orders(today)                [portfolio/simulator]
  │    → orders pending from yesterday fill at ATO today
  │    → compute fees, update holdings + cash
  │
  ├─ check_stop_loss(today)                    [portfolio/simulator]
  │    → any holding > -8% → auto SELL proposal with source='simulator_auto'
  │
  ├─ [DAILY_RESEARCH_MODE dispatch]            [scheduler/jobs]
  │    │
  │    ├─ "single" (default)  → daily_research_single_job:
  │    │     Claude agent reads skills + watchlist + holdings
  │    │     → emit proposals via `propose_trade` tool (buffered)
  │    │
  │    └─ "swarm"             → daily_research_swarm_job:
  │          orchestrator.run_preset("daily_research"):
  │            snapshot → researcher → record_memory
  │
  ├─ validator.validate_batch(proposals)        [portfolio/validator]
  │    Pydantic + business rules + playbook checklist
  │    accepted ∪ rejections → persist rejection reasons
  │
  ├─ insert_decision + place_order_from_decision  (per accepted)
  │    → decisions table (with trace_id if from swarm)
  │    → orders.status='pending', expected_fill_date=next trading day
  │    → bump skill_scores.uses for each skill_used
  │
  ├─ record_event(kind='observation',           [memory/events]
  │     summary=agent text, trace_id=…)
  │
  ├─ compute_equity(today)                      [portfolio/simulator]
  │    → daily_equity row (cash, mv, total, VN-Index)
  │
  └─ telegram.send_report → /today result
       + heartbeat: "✅ N decisions, M rejected, tokens=…, trace_id=…"
```

## Data flow — weekly review

```
Sunday 10:00 Asia/Ho_Chi_Minh (cron)
  │
  ├─ run_weekly_review()                       [learning/weekly_review]
  │    Claude agent reads decisions+outcomes+strategy.md
  │    → may append strategy.md + edit skills/*.md (≤ 2 / week)
  │    → git add skills/ strategy.md && git commit (done outside)
  │
  ├─ compute_and_persist_all(lookback=180d)    [learning/skill_stats_compute]
  │    For each skill seen in decisions 180d:
  │      fetch outcomes (pnl_pct_20d)
  │      → bootstrap_ci(win_rate, n=500)
  │      → monte_carlo_permutation(pnl_pct, n=500)
  │      → walk_forward(pnl_pct, n_windows=3..5)
  │    UPSERT skill_scores_v2 (ci_low/high, mc_pvalue, wf_pass_count)
  │
  ├─ run_bot_bias_check(lookback=90d)          [bias/weekly_check]
  │    load_bot_trades (FIFO pairing orders→trades)
  │    load_bot_decisions (ticker+action+skills)
  │    → detect_all(...) → 7 BiasResult
  │    → persist to bias_reports (upsert by (scope,week,bias))
  │
  ├─ apply_all()                               [learning/skill_lifecycle]
  │    For each skill file:
  │      evaluate_skill() per FSM
  │      if status changed (shadow→active or active→archived):
  │        rewrite frontmatter status line
  │        insert skill_lifecycle_transitions audit row
  │
  ├─ extract_patterns()                        [memory/patterns]
  │    TTL delete stale unconfirmed patterns (>90d)
  │    scan winners (pnl_pct > 0) in last 90d
  │    cluster by (skill_combo, playbook, conviction_bucket)
  │    ≥ 3 winners → upsert patterns row
  │
  ├─ propose()                                 [learning/skill_proposer]
  │    read unconfirmed patterns (support ≥ 3)
  │    emit ≤ 2 SkillDraft (log-only, NOT materialized)
  │
  └─ telegram.send_weekly_summary
       + stats computed, bias flags, lifecycle changes, proposed drafts
```

---

## Boundaries

- `research/` is the only module that imports `claude_agent_sdk`.
- `db/queries.py` is the only module issuing raw SQL. Others use typed helpers.
- `telegram/` never touches `portfolio/simulator` directly — route through
  `portfolio/reporter` for rendered output.
- `orchestrator/` is the only module that runs multi-agent DAGs. Single-
  agent fallback stays in `research/agent.py`.
- `memory/` owns all reads/writes to `data/memory/*.md` + `events_fts`.
  Other modules use `search_memory`, `get_timeline`, `write_memory`.
- `shadow/` parses broker CSV only through `shadow/parsers/*`. Never parse
  inside `telegram/` or `research/`.
- `bias/detectors.py` is pure: `list[Trade]/list[Decision] → list[Result]`.
  No DB, no persistence. `bias/weekly_check.py` is the only DB-aware caller.
- `learning/stats.py` is the only place that imports numpy for statistics.
  Skill lifecycle transitions MUST go through `skill_lifecycle.py` — never
  write `skill_scores_v2.status` directly.
- `mcp/server.py` exposes READ-ONLY tools only. Never expose `propose_trade`,
  `write_skill`, `append_strategy_note`, or any file-write tool.
- DuckDB `ATTACH` SQLite in READ-ONLY mode. Views in `db/duckdb_views.sql`.
- Money conversions (VND ↔ display string) only in `telegram/format.py`.

---

## Invariants

1. **No lookahead.** Research agent sees data only up to today's close;
   orders fill at next trading day ATO.
2. **T+2 settlement.** `holdings.qty_available` ≤ `holdings.qty_total`.
   SELL/TRIM only against `qty_available`.
3. **Biên độ.** Price bands: ±7% HSX, ±10% HNX, ±15% UPCOM. Validator
   rejects any price out of band.
4. **int VND everywhere.** No floats in DB, simulator, validator, portfolio.
5. **Position caps.** ≤20% NAV/mã, ≤10 vị thế, ≤2 mã/sector.
6. **Stop -8% hard.** Overriding requires logging reason + playbook ref.
7. **Validate before persist.** Decision only hits DB after validator.
8. **Idempotent daily job.** Re-running same day doesn't double-fill
   (`orders.status` + `daily_equity.date UNIQUE`).
9. **Statistical gate for skill promotion.** shadow → active only via
   `skill_lifecycle.py`. Gate: ≥30 uses AND `ci_low > 0.5` AND walk-forward
   ≥3/5 AND beat parent ≥2% absolute win-rate.
10. **DAG replay determinism.** `trace_id` + seed + cached data reproduce
    identical output for the same input.
11. **Bias flags are advisory, not blocking.** Do NOT auto-reject based on
    bias. Calibrate via weekly review.
12. **Shadow skills are log-only.** Shadow skill never creates pending
    orders; it runs parallel to active and compares outcomes.
13. **MCP read-only.** No exposed tool may mutate state.
14. **Skill edit budget.** ≤ 2 skills edited per weekly review. Bump
    `version`. Deprecated rules go to `## Deprecated rules` section — not
    silently deleted.
15. **Git commit** after skill/strategy edits in weekly review.
16. **Whitelist chat IDs.** One user, no multi-tenancy.

---

## SQLite schema (by concern)

### Portfolio state
- `meta(key, value)` — cash, misc singletons
- `holdings(ticker, qty_total, qty_available, avg_cost, opened_at, last_buy_at)`
- `orders(id, decision_id, ticker, side, qty, placed_at, expected_fill_date, filled_at, fill_price, fee, status)`
- `daily_equity(date, cash, market_value, total, vnindex, notes)` — `UNIQUE (date)`

### Decisions + outcomes
- `decisions` — full proposal including v2 fields: `trace_id`,
  `target_bear/base/bull`, `bias_flags_json`
- `decision_outcomes(decision_id, days_held, pnl_pct, thesis_valid, invalidation_hit, scored_at)` — scored at 5/10/20d
- `skill_scores` (legacy v1) — simple uses/wins
- `skill_scores_v2` — v2 stats: status, parent_skill, ci_low/high,
  mc_pvalue, wf_pass_count, shadow_vs_parent
- `skill_lifecycle_transitions` — audit log of every state change

### Market data
- `market_snapshot(date, vnindex_ohlc, foreign_buy, foreign_sell, top_movers_json)`
- `ohlc_cache(ticker, date, o, h, l, c, v)` — DAG-replay source of truth

### Memory (L1-L4)
- `events(id, created_at, kind, ticker, decision_id, trace_id, summary, payload_json)`
- `events_fts` — FTS5 virtual table (unicode61 + remove_diacritics)
- `summaries(id, scope, key, body, event_count)` — L3, UNIQUE (scope, key)
- `patterns(id, body, support_count, confirmed, last_seen_at, metadata_json)` — L4, TTL 90d

### Chat
- `chat_history(id, chat_id, role, content, created_at)`

### DAG execution
- `dag_traces(trace_id, preset, status, started_at, ended_at, elapsed_ms, variables_json, final_output_json)`
- `dag_node_results(trace_id, node_id, status, started_at, ended_at, elapsed_ms, output_json, error)`

### Bias + Shadow
- `bias_reports(scope, week_of, bias_name, severity, metric, thresholds, evidence)` — UNIQUE (scope, week_of, bias_name)
- `shadow_accounts(shadow_id, broker, journal_path, uploaded_at, total_trades, real_pnl, …)`
- `shadow_rules(shadow_id, rule_id, human_text, support_count, coverage_rate, …)` — UNIQUE (shadow_id, rule_id)
- `shadow_backtests(shadow_id, run_at, real_pnl, shadow_pnl, delta_pnl, components…, report_html_path)`

### DuckDB views (optional)
Read-only views over SQLite ATTACH. See `db/duckdb_views.sql`:
- `v_equity_rolling` — 20/60d rolling Sharpe, DD
- `v_skill_ci` — latest stats per skill + last transition
- `v_decision_attrib` — per-decision PnL + skills + outcome
- `v_regime_labels` — regime timeline from `macro_sector_desk` traces

---

## External integrations

| External | Used where | Auth |
|---|---|---|
| Telegram Bot API | `telegram/bot.py` (long-poll) | Bot token (from @BotFather) |
| Claude Agent SDK | `research/agent.py` | Claude Code CLI session (OAuth, `claude login`) |
| vnstock | `data/vnstock_client.py` | None (public VCI/TCBS) |
| MCP clients | `mcp/server.py` (stdio) | Local process, no network |

---

## Files cheat sheet

| Concern | File |
|---|---|
| Config + env | `config.py` |
| CLI entry | `main.py` |
| Telegram core | `telegram/bot.py` |
| Telegram commands | `telegram/v2_handlers.py` |
| VNStock wrapper | `data/vnstock_client.py` |
| Market snapshot | `data/market_snapshot.py` |
| Holiday check | `data/holidays.py` |
| DB schema | `db/schema.sql` |
| DB helpers | `db/queries.py` |
| Simulator | `portfolio/simulator.py` |
| Validator | `portfolio/validator.py` |
| Scheduled jobs | `scheduler/jobs.py` |
| Claude agent | `research/agent.py` |
| Claude tools | `research/tools.py` |
| DAG runner | `orchestrator/dag.py` |
| Preset loader | `orchestrator/preset_loader.py` |
| Node factories | `orchestrator/nodes.py` |
| Function handlers | `orchestrator/builtins.py` |
| Skill loader | `research/skill_loader.py` |
| Skill lifecycle | `learning/skill_lifecycle.py` |
| Skill stats compute | `learning/skill_stats_compute.py` |
| Statistical lib | `learning/stats.py` |
| Skill proposer | `learning/skill_proposer.py` |
| Weekly review | `learning/weekly_review.py` |
| Decision scorer | `learning/scorer.py` |
| Bias detectors | `bias/detectors.py` |
| Bias weekly check | `bias/weekly_check.py` |
| Memory events | `memory/events.py` |
| Memory files | `memory/files.py` |
| Memory recall | `memory/recall.py` |
| L4 patterns | `memory/patterns.py` |
| FTS5 wrapper | `memory/fts5.py` |
| Compression | `memory/compression.py` |
| Shadow tools | `shadow/__init__.py` |
| Shadow parsers | `shadow/parsers/` |
| FIFO pairing | `shadow/pairing.py` |
| Rule extractor | `shadow/rule_extractor.py` |
| Delta-PnL | `shadow/delta_pnl.py` |
| HTML report | `shadow/report.py` |
| Backtest runner | `backtest/runner.py` |
| Backtest metrics | `backtest/metrics.py` |
| Optimizers | `backtest/optimizers.py` |
| Backtest validation | `backtest/validation.py` |
| Pine generator | `export/pine_script.py` |
| MCP server | `mcp/server.py` |
