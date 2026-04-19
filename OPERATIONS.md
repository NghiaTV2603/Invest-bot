# Operations — cách vận hành chi tiết

> Doc này trả lời câu hỏi **"bot chạy thật sự như thế nào từng bước?"** —
> từ cron fires tới decision persisted tới skill promoted. Nếu bạn đọc
> [ARCHITECTURE.md](ARCHITECTURE.md) xong rồi, đây là phần mechanics.

Mục lục:
1. [Runtime model](#1-runtime-model)
2. [Boot sequence](#2-boot-sequence)
3. [Daily research lifecycle](#3-daily-research-lifecycle)
4. [Weekly review lifecycle](#4-weekly-review-lifecycle)
5. [Swarm DAG execution](#5-swarm-dag-execution)
6. [Skill lifecycle FSM](#6-skill-lifecycle-fsm)
7. [Shadow Account pipeline](#7-shadow-account-pipeline)
8. [Memory reads & writes](#8-memory-reads--writes)
9. [Validation + simulator](#9-validation--simulator)
10. [Bias detection](#10-bias-detection)
11. [Observability](#11-observability)
12. [Failure modes & fallbacks](#12-failure-modes--fallbacks)
13. [Troubleshooting quick-ref](#13-troubleshooting-quick-ref)

---

## 1. Runtime model

**Một Python process, một event loop asyncio.** Không có thread pool, không
có multi-process. Mọi I/O (Telegram long-poll, Claude SDK streaming, vnstock
HTTP, SQLite) dùng asyncio primitives.

```
python -m vnstock_bot.main run  (entry: main.cli → asyncio.run(_run_bot))
       │
       ├─ telegram.Application   long-poll HTTP
       ├─ APScheduler (AsyncIO)  2 cron jobs
       └─ asyncio.Event           → stop signal
```

- **SQLite** kết nối 1 global connection (autocommit, WAL). `transaction()`
  context manager wrap BEGIN/COMMIT/ROLLBACK. Không connection pool —
  SQLite cho phép multi-reader + 1-writer, phù hợp single-process bot.
- **Claude SDK** streaming messages qua `async for msg in receive_response()`.
  Mỗi agent turn block event loop cho đến khi Claude xong.
- **APScheduler** dùng `AsyncIOScheduler` — job được add vào cùng event loop
  bằng `asyncio.create_task`. Cron fires, job queued, chạy giữa các Telegram
  polling iterations.

**Single-writer implication:** nếu daily_research đang chạy (~30-60s) và
user nhắn Telegram, bot sẽ phản hồi **sau khi** daily xong. Đây là OK cho
bot cá nhân; nếu cần parallelism, kiến trúc sẽ phức tạp hơn đáng kể.

---

## 2. Boot sequence

```
vnstock-bot run
  │
  ├─ main.cli()
  │    parse args
  │    setup_logging(level, log_dir) — structlog → JSON → logs/
  │    asyncio.run(_run_bot())
  │
  └─ _run_bot()
       │
       ├─ get_settings() (pydantic-settings, reads .env)
       │    Creates data/, logs/, data/memory/ dirs if missing.
       │
       ├─ build_application()
       │    Creates Telegram Application (long-poll)
       │    Registers v1 handlers: /start /status /today …
       │    register_v2_handlers(app):
       │      /shadow /bias /recall /why /regime /debate /review
       │      /today_swarm /skill /export + Document(csv) handler
       │
       ├─ AsyncIOScheduler(timezone=settings.tz)
       │    Add daily_research_job   CronTrigger(15:30 Mon-Fri)
       │    Add weekly_review_job    CronTrigger(Sun 10:00)
       │    scheduler.start()
       │
       ├─ app.initialize() → start() → updater.start_polling()
       │
       ├─ send_default("🤖 vnstock-bot online")
       │
       └─ await asyncio.Event()  (parks forever until Ctrl-C)
```

### Lazy imports
Nhiều hot-path imports là **lazy** (trong function body, không top-of-file):
- `from vnstock_bot.research.agent import chat as chat_agent` — trong
  `telegram.on_message`
- `from vnstock_bot.orchestrator import run_preset` — trong `cmd_debate`

Lý do: `research/agent.py` import `claude_agent_sdk` là expensive + fails
hard nếu `claude login` chưa chạy. Lazy import giữ `vnstock-bot doctor` và
test suite chạy được khi SDK chưa auth.

---

## 3. Daily research lifecycle

Cron fires 15:30 thứ 2-6. Ngày lễ (`data/holidays.py`) skip.

### Step 1. Dispatcher (`scheduler/jobs.py`)
```python
async def daily_research_job(send):
    settings = get_settings()
    if settings.daily_research_mode == "swarm":
        return await daily_research_swarm_job(send)
    return await daily_research_single_job(send)
```
`DAILY_RESEARCH_MODE` env — default `"single"`. Flip sang `"swarm"` khi đã
verify swarm path stable via `/today_swarm` manual run.

### Step 2. Market prep (cả 2 paths)
```python
build_snapshot(today)           # data/market_snapshot
release_t2_shares(today)        # holdings.qty_available += shares past T+2
fill_summary = fill_pending_orders(today)   # ATO fills from yesterday
auto_proposals = check_stop_loss(today)     # -8% hard stop emitter
```

- `build_snapshot` gọi `vnstock_client.fetch_index("VNINDEX")` + aggregates
  foreign flow + top movers into `market_snapshot` row.
- `release_t2_shares` runs `UPDATE holdings SET qty_available = qty_total
  WHERE date(last_buy_at, '+2 days') <= ?`.
- `fill_pending_orders` cho mỗi `orders.status='pending'` với
  `expected_fill_date=today`: fetch OHLC hôm nay, fill price = open, fee =
  qty × price × bps / 10000. Update holdings (weighted avg cost) + cash.
- `check_stop_loss` scan holdings, so close hiện tại với `avg_cost`. Mã
  lỗ > 8% → tạo `{"action": "SELL", "source": "simulator_auto",
  "playbook": "cut-loser", "conviction": 5}`, đẩy vào validator chain chung
  (đã qua `insert_decision + place_order_from_decision`).

### Step 3a. Single-agent path (`daily_research_single_job`)
```python
ctx = _build_daily_context()    # watchlist OHLC + holdings + snapshot + cash
from vnstock_bot.research.agent import daily_research
result, proposals = await daily_research(ctx)
```

`daily_research()` → `run_agent()`:
- Build in-process MCP server exposing 7 tools (`load_skill`, `get_price`,
  `get_fundamentals`, `market_snapshot`, `get_portfolio_status`,
  `propose_trade`, `list_skills`).
- `ClaudeSDKClient` với `permission_mode="bypassPermissions"`.
- Claude turn loop: `await client.query(user_prompt)` → stream
  `AssistantMessage` / `ResultMessage`. Each `propose_trade` tool call
  pushes into `_proposal_buffer` — **NOT persisted yet**.
- Loop ends → return `AgentResult(text, turns, tokens_used)` + flush
  `get_proposals()`.

### Step 3b. Swarm path (`daily_research_swarm_job`)
```python
result = await run_preset("daily_research",
                          variables={"watchlist_context": ctx},
                          agent_fn=make_default_agent_fn(),
                          listeners=[_on_event])
```

Preset `config/swarm/daily_research.yaml` có 3 node: `snapshot` (function)
→ `researcher` (agent) → `record_memory` (function). Orchestrator wave
execution (xem §5).

Streaming events về Telegram qua `_on_event(ev)` callback. User thấy
`⏳ researcher → ✅ researcher (8234 ms)`.

### Step 4. Validator chain
```python
accepted, rejections = validate_batch(proposals)
```

`portfolio/validator.py::validate_batch`:
1. Pydantic `DecisionInput` (ticker upper, qty ≥ 0, conviction 1-5).
2. Business rules:
   - `ticker ∈ watchlist`
   - `qty % 100 == 0` (lot size HSX)
   - `target_price, stop_loss` trong biên độ sàn (±7/±10/±15)
   - `cash ≥ qty × price + fee` (buy power check)
   - position cap 20% NAV/mã
   - ≤ 10 vị thế đồng thời
   - ≤ 2 mã cùng sector (correlation-check skill mirror)
3. Playbook check: nếu `action=BUY` và `playbook=new-entry`, verify
   evidence list ≥ 3 bullets.

Rejected decisions logged với lý do → gửi Telegram cuối report.

### Step 5. Persist
```python
for dec in accepted:
    did = queries.insert_decision({..., "trace_id": result.trace_id})
    queries.bump_skill_uses(dec.skills_used, iso(today))
    place_order_from_decision(did, dec, today)
    record_event(kind="decision", summary=..., decision_id=did,
                 trace_id=result.trace_id)
```

- `insert_decision` ghi decisions table (với cả v2 columns: trace_id,
  target_bear/base/bull, bias_flags_json).
- `place_order_from_decision` tạo orders row status='pending',
  `expected_fill_date = next_trading_day(today)`.
- `bump_skill_uses` bump `skill_scores.uses` cho mỗi skill trong
  `skills_used`.
- `record_event` → events L1 + FTS5 index.

### Step 6. Equity snapshot
```python
snap = queries.latest_market_snapshot()
stats = compute_equity(today, vnindex=snap["vnindex_close"])
```

`compute_equity` tính `cash + mv` (mv = Σ qty × latest_close), insert
`daily_equity` row `UNIQUE (date)` — chạy lại cùng ngày không duplicate.

### Step 7. Telegram report
```python
report_md = reporter.daily_report(today, created_decisions, rejections,
                                   fill_summary.filled, stats)
await send(report_md)
await send(f"✅ daily_research OK — {len(accepted)} decisions, "
           f"{len(rejections)} rejected, {result.turns} turns, "
           f"~{result.tokens_used} tokens")
```

User thấy:
- 📈 NAV + P&L + vs VN-Index
- Mỗi decision: `d#42 BUY FPT qty=100 @ target 160k stop 137k`
- Rejections với reason
- Heartbeat metadata

### Step 8. Swarm-specific: trace persist
Nếu swarm mode: `dag_traces` + `dag_node_results` rows đã được ghi bởi
`orchestrator/dag.py` trong quá trình chạy. User có thể `/why <trace_id>`
hoặc `/why d<decision_id>` để replay.

---

## 4. Weekly review lifecycle

Cron fires chủ nhật 10:00. 6-step pipeline.

### Step 0. Legacy weekly review
```python
summary = await run_weekly_review()   # learning/weekly_review.py
```
Claude agent đọc `decisions + outcomes + skill_scores (v1) + strategy.md`.
Output: `append_strategy_note` + optionally `write_skill` (≤ 2 skills).
Tools buffered, flushed after turn loop, written to filesystem + git
committed ngoài function này.

### Step 1. Compute CI + WF per skill (`learning/skill_stats_compute.py`)
```python
stats_rows = compute_and_persist_all(lookback_days=180)
```

Logic:
1. `_distinct_skills_seen(since)` — SELECT DISTINCT skills_used_json → JSON
   parse → union set of skill names seen in 180d.
2. Với mỗi skill:
   a. `_fetch_outcomes_for_skill(skill, since)` — decisions có
      `skills_used_json LIKE '%"skill"%'`, JSON-verify (guard substring
      false-match), join với `decision_outcomes` latest-horizon ≤ 20d.
   b. `uses = len(records)`. Nếu `< MIN_USES_TO_COMPUTE (5)` → row với
      `win_rate_ci_low=NULL` (lifecycle sẽ trả `insufficient_trades`).
   c. `outcomes = (pnl_pct > 0).astype(float)` → binary win/loss series.
   d. `bootstrap_ci(outcomes, stat_fn=win_rate, n_bootstrap=500)` →
      (point, ci_low, ci_high).
   e. `monte_carlo_permutation(pnl_pct, stat_fn=win_rate, n_permutations=500)`
      → p-value.
   f. `walk_forward(pnl_pct, n_windows=3|5, threshold=0.5)` → pass_count.
3. Resolve skill name: bare name ("momentum") → path ("strategy/momentum")
   nếu exactly 1 file match. `UPSERT skill_scores_v2` bằng path name.

**Why this must run BEFORE lifecycle:** nếu skill_scores_v2 chưa có ci_low,
`skill_lifecycle.evaluate_skill` sẽ trả `insufficient_trades` cho mọi
shadow-status skill → không có transition nào xảy ra.

### Step 2. Bias check (`bias/weekly_check.py`)
```python
bias_results = run_bot_bias_check(persist=True)
```

Logic:
1. `load_bot_trades(days=90)` — query orders filled trong 90d, FIFO pair
   BUY→SELL theo ticker, attach pnl + hold_days + entry_price cho SELL.
2. `load_bot_decisions(days=90)` — parse `skills_used_json` cho mỗi
   decision, build `DecisionLike`.
3. `detect_all(trades, decisions)` → 7 BiasResult (disposition, overtrading,
   chase_momentum, anchoring, hot_hand, skill_dogma, recency) với severity
   low/medium/high + metric + threshold_medium/high + evidence.
4. `persist_report(scope="bot", week_of=monday, results)` → UPSERT
   `bias_reports` (UNIQUE scope, week_of, bias_name).

Xem formulas chi tiết ở §10.

### Step 3. Skill lifecycle (`learning/skill_lifecycle.py`)
```python
lifecycle_decisions = apply_all(dry_run=False)
```

Logic:
1. `evaluate_all()` — cho mỗi skill trong `list_all_skills()`:
   - `evaluate_skill(name)` = `read_skill_meta + _load_stats_row + apply_FSM`.
   - FSM per current status (xem §6).
2. For each decision where `changed=True`:
   - `_bump_frontmatter_status(name, to_status)` — regex rewrite status:
     line, write back.
   - `_record_transition(d)` — INSERT `skill_lifecycle_transitions` row +
     UPDATE `skill_scores_v2.status`.

### Step 4. L4 pattern extraction (`memory/patterns.py`)
```python
pattern_summary = extract_patterns()
```

Logic:
1. `_delete_stale()` — DELETE unconfirmed patterns `last_seen_at > 90d`.
2. `_fetch_winning_decisions(since_iso=90d ago)` — decisions
   `pnl_pct_20d > 0 AND action IN ('BUY','ADD')`.
3. `_extract_candidates(winners)` — group by
   `(skill_combo, playbook, conviction_bucket)`. Clusters ≥ 3 → emit
   `PatternCandidate(body, support, metadata)`.
4. `_upsert(candidate)` — dedup by `body` text (cheap). Existing row →
   bump support_count + last_seen_at. New → INSERT.

### Step 5. Skill proposer (`learning/skill_proposer.py`)
```python
proposed_drafts = propose()   # read-only: log drafts, no file writes
```

Logic:
1. `_load_candidate_patterns(days=30)` — patterns support ≥ 3, confirmed=0.
2. Per pattern: `_build_draft(pattern, idx)` với frontmatter v2 đủ fields.
3. Dedup against `list_all_skills()`, return ≤ `MAX_DRAFTS_PER_WEEK (2)`.

**Important:** `propose()` does NOT write files. Human must `/skill promote
<draft-name>` → `human_promote_draft_to_shadow` OR explicitly call
`materialize_draft(d)` to put it on disk. Gate là cố ý — auto-emit skill
files = auto-bloat git.

### Step 6. Telegram summary
```python
📅 Weekly review — 2026-04-19
Strategy notes: +3
Skill edits: 1
Tokens: 28500

📊 Stats computed: 8 skills (5 have CI)
Top skills: breakout, foreign-flow, technical-trend
Bottom skills: mean-reversion

🏴 Bias high flags: 1 (disposition_effect)
🔁 Lifecycle changes: 2 (strategy/breakout: shadow→active, strategy/rsi-mr: active→archived)
💡 Proposed drafts: 1 (strategy/vol-surge-draft-1)
```

---

## 5. Swarm DAG execution

### 5.1 Preset → DagSpec

`orchestrator/preset_loader.load_preset(name)`:
1. Read YAML at `config/swarm/<name>.yaml`.
2. `DagSpec(**yaml)` — Pydantic validation:
   - Unique node IDs.
   - All `depends_on` reference known nodes.
   - All `input_from` values reference known nodes.
3. `validate_variables(spec, {})` — enforce required vars, apply defaults.

### 5.2 Topological wave sort

`dag._topo_levels(spec)` — Kahn's algorithm:
- `in_deg[n] = len(n.depends_on)`.
- Nodes with `in_deg=0` form wave 0.
- Remove wave nodes → recompute → wave 1.
- Repeat until empty. Cycle → `ValueError` at wave-build time.

### 5.3 Wave execution

```python
for wave in _topo_levels(spec):
    # Skip nodes whose deps didn't succeed
    active = [n for n in wave if all(prior[d].status == "success"
                                      for d in n.depends_on)]
    skipped_nodes = wave - active  # marked status='skipped'

    # Parallel within wave
    results = await asyncio.gather(*[
        _run_single_node(n, runner, variables, prior, trace_id, bus)
        for n in active
    ])
    for r in results:
        prior[r.node_id] = r
        persist_node_result(trace_id, r)
```

Per-node execution:
1. Resolve `input_from` → upstream outputs into `ctx.upstream`.
2. `asyncio.wait_for(runner.run(ctx), timeout=node.timeout_seconds)`.
3. On success: `NodeResult(status="success", output=...)`.
4. On `TimeoutError`: `status="timeout"`.
5. On any other exception: `status="failed"`.
6. Emit `node_end` or `node_fail` event.

### 5.4 DAG-level timeout

Outer `asyncio.wait_for(_exec_all(), timeout=spec.timeout_seconds)` wraps
the whole run. If tripped, unfinished nodes marked `timeout`.

### 5.5 Trace persistence

Every run creates 1 `dag_traces` row + 1 `dag_node_results` row per node.
Persist happens **outside** the main transaction so an FTS5 corruption
(rare) doesn't block business writes.

`load_trace(trace_id)` replays by joining dag_traces + dag_node_results.

### 5.6 Streaming

`EventBus` fan-out. Each node start/end/fail emits `StreamEvent` asynchronously.
Listener exceptions are suppressed (`contextlib.suppress`) — one bad
listener can't crash the DAG. Telegram uses this to show progress:
`⏳ researcher → ✅ researcher (8234 ms) → ⏳ risk_officer`.

---

## 6. Skill lifecycle FSM

State diagram:
```
       [Draft]
          │  /skill promote <name>   (human)
          ▼
       [Shadow] ──── insufficient stats ──── stays Shadow
          │
          │  stat gate pass
          │   (≥30 uses AND ci_low>0.5 AND wf_pass≥3/5
          │    AND if parent: beat_parent≥2%)
          ▼
       [Active] ─── active→active by default, auto-demote only if
          │         bad stats (ci_high<0.5 with ≥30 uses)
          │
          ▼
     [Archived] ─── human revive → [Shadow]
```

### 6.1 `evaluate_skill(name)`

```python
def evaluate_skill(skill_name: str) -> LifecycleDecision:
    meta = read_skill_meta(skill_name)
    stats = _load_stats_row(skill_name)

    if meta.status == "shadow":
        return _evaluate_shadow_to_active(name, "shadow", stats)
    if meta.status == "active":
        return _evaluate_active_to_archived(name, "active", stats)
    if meta.status in ("draft", "archived"):
        return LifecycleDecision(from=..., to=..., reason="human_approval")
    return no-op
```

### 6.2 Shadow → Active gate

```python
if uses < 30:                          → insufficient_trades
if ci_low <= 0.5:                      → stat_gate_fail_low_ci
if wf_pass_count < 3:                  → stat_gate_fail_low_ci
if parent and shadow_vs_parent < 0.02: → parent_beat_insufficient
else:                                  → to_status = "active"
```

Rationale:
- ≥30 uses: bootstrap CI has ~reasonable width.
- ci_low > 0.5: at 95% confidence we believe win-rate > 50% (beats naive
  coin-flip even at pessimistic bound).
- walk-forward ≥3/5: skill generalizes across time windows (not just
  lucky in one sub-period).
- beat parent ≥2%: if this skill forked from a parent, it must actually
  outperform — avoid parent-creep.

### 6.3 Active → Archived gate

```python
if uses < 30:           → no_change_needed
if ci_high >= 0.5:      → no_change_needed
else:                   → to_status = "archived"
```

Only archive when we're confident (95% CI upper bound) win-rate ≤ 50% AND
we have enough samples. Avoids ping-ponging skills that had a bad streak.

### 6.4 Apply a decision

```python
def apply_decision(d):
    if not d.changed: return False
    _bump_frontmatter_status(d.skill, d.to_status)
      # Regex rewrite: ^status:\s*\w+\s*$ → status: <new>
      # Preserve all other frontmatter + body byte-identical
    _record_transition(d)
      # INSERT skill_lifecycle_transitions
      # UPDATE skill_scores_v2.status
```

Git commit happens **outside** (caller weekly_review). Note: if
`_bump_frontmatter_status` throws (no frontmatter found), the skill is
skipped — check logs.

### 6.5 Human operations

- `human_promote_draft_to_shadow(name, note)` — only `draft → shadow`.
  `/skill promote <name>` wires to this.
- `human_revive_archived(name, note)` — only `archived → shadow`. Not
  exposed in Telegram; must call programmatically.

---

## 7. Shadow Account pipeline

### 7.1 Trigger

User attaches a `.csv` file to Telegram chat. `telegram/v2_handlers.py`
filter `filters.Document.FileExtension("csv")` routes to `on_document`.

### 7.2 Download + dispatch

```python
tg_file = await doc.get_file()
await tg_file.download_to_drive(custom_path=str(target))
# target = data/shadow/<YYYYMMDD_HHMMSS>_<filename>.csv

ext = shadow.extract_shadow_strategy(target)
bt = shadow.run_shadow_backtest(ext["shadow_id"], ext)
html_path = shadow.render_shadow_report(ext["shadow_id"], ext, bt)
```

### 7.3 Parse (`shadow/parsers/`)

1. `detect_broker(path)` — peek first row → match `SSIParser.detect(header)`
   → `VPSParser` → `TCBSParser` → fallback `GenericParser`.
2. Parser's `COLUMN_MAP` resolves header aliases → column indices.
3. Per row:
   - `to_int(value)` handles VN thousands-dot (`148.500` → 148500),
     commas (`148,500`), whitespace.
   - `parse_datetime` tries 8 formats (EN/VN).
   - `parse_side` maps `Mua|Bán|Mua khớp|Bán khớp|BUY|SELL` → canonical.
4. Rows failing validation are **skipped** (not thrown) so one bad row
   doesn't nuke the whole import.

### 7.4 Pairing (`shadow/pairing.py`)

Sort trades by `traded_at`. Per ticker maintain a FIFO queue of open
buys. Each SELL drains the queue:
```
BUY 200 @ 100000 ──┐
BUY 100 @ 105000 ──┤
                  │
SELL 150 @ 110000 ◄── take 150 from head:
                      - 150 from BUY#1 (still 50 left)
                      - queue: [BUY#1 50cp @ 100k, BUY#2 100cp @ 105k]
                      → Roundtrip(qty=150, buy_price=100k, sell_price=110k,
                                   buy_fee_slice, sell_fee_slice)
```

Fee apportioning: fee proportional to qty fraction. Last slice gets
remainder to avoid rounding drift.

### 7.5 Rule extraction (`shadow/rule_extractor.py`)

```python
winners = [r for r in roundtrips if r.is_winner]
global_win_rate = len(winners) / len(roundtrips)

# 3-axis cluster
groups[(sector, hour_bucket, hold_bucket)] = list[Roundtrip]

for key, cluster_winners in groups.items():
    if len(cluster_winners) < 3: continue
    lift = cluster_win_rate - global_win_rate
    if lift < 0: continue   # cluster worse than user's baseline
    score = len(cluster_winners) * (1 + lift)
    emit ShadowRule(human_text ≤ 30 chars, ...)

return top-N (default 5) by score
```

Hour buckets: `sáng sớm (9-10), sáng muộn (10-11), chiều sớm (13-14),
chiều muộn (14-15)`. Hold buckets: `1, 2-5, 6-10, 11-30, dài hạn`.

### 7.6 Delta-PnL attribution (`shadow/delta_pnl.py`)

For each roundtrip:
1. Group by buy-day. Trades #3+ in the same day → `overtrading_pnl`.
2. `_match_any(rt, rules)` — returns first rule whose **setup** (sector +
   hour) matches. Hold mismatch is NOT noise — it becomes early/late exit.
3. If no setup match → `noise_trades_pnl += rt.pnl`.
4. If match + winner + hold < rule.min → `early_exit_pnl += proportional
   upside missed`.
5. If match + loser + hold > rule.max → `late_exit_pnl += proportional
   loss that would've been capped`.

**Shadow PnL model:**
```
shadow_pnl = rule_conforming_pnl
           + early_exit_pnl       (winners held to rule min)
           + late_exit_pnl        (losers cut at rule max)
           # MINUS noise + overtrading trades (user wouldn't have taken)
```

### 7.7 HTML report (`shadow/report.py`)

No template engine. Pure f-string with inline CSS + inline SVG for equity
curve. 8 sections with anchor IDs `s1..s8` — tests verify every section
is rendered.

Output: `data/reports/shadow/<shadow_id>.html`. User opens in browser.
PDF: browser print-to-PDF (native). No WeasyPrint dep.

---

## 8. Memory reads & writes

### 8.1 Who writes to L1 events
- `research/tools.py` — each tool call
- `scheduler/jobs.py` — decision creation
- `orchestrator/builtins.py::record_research_event` — swarm DAG
- Any module can call `memory.record_event(kind, summary, ...)`.

### 8.2 Who writes to L2 files (`data/memory/user_prefs/*.md`)
- `/skill promote` → nothing (that's skill files, not memory).
- User explicitly via `memory.write_memory_file(...)` — rare.
- Future: `learning/weekly_review` may surface insights here.

### 8.3 Who writes to L3 summaries
**Currently no automatic writer.** Schema exists; `compression.py` reads;
writer would live in `scheduler/jobs.py` end-of-day (deferred).

### 8.4 Who writes to L4 patterns
- `memory/patterns.py::extract_and_persist` — weekly from winning decisions.
- TTL 90d for unconfirmed rows.

### 8.5 Who reads memory
- `research/agent.py` via `search_memory` + `recall_similar_decision` tools.
- `memory/compression.py` builds a 5-layer context when prompt budget tight.
- Telegram `/recall` + `/why`.

### 8.6 FTS5 internals
- Virtual table `events_fts` with `content_rowid='id'` (internal content).
- Tokenizer `unicode61 remove_diacritics 2` → strips VN diacritics,
  case-folds. `đ/Đ` not handled by NFD → Python `tokenizer.normalize`
  mirrors with manual `_LATIN_FOLDS` map.
- Query: `bm25(events_fts, 2.0, 1.0)` — summary weighted 2× over payload_text.
- Query sanitizer: user input → tokenize → `OR`-join tokens. Raw input
  with `AND`/`OR`/quotes would break FTS5 MATCH syntax.
- Rebuild: `fts5.rebuild_index()` — `DELETE + INSERT FROM events`. Weekly
  cron doesn't do this automatically; call manually if drift suspected.

---

## 9. Validation + simulator

### 9.1 Validator chain (`portfolio/validator.py`)

Every proposal (Claude OR simulator_auto OR user_manual) passes:
```
Pydantic schema         — types, ranges
│
Watchlist               — ticker ∈ config/watchlist.yaml
│
Lot size                — qty % 100 == 0 (HSX)
│
Price band              — target_price, stop_loss ∈ [close × (1-band), close × (1+band)]
│
Buying power            — for BUY: cash ≥ qty × price × (1+fee)
│
Position cap            — post-trade, ticker weight ≤ 20% NAV
│
Portfolio cap           — ≤ 10 positions
│
Sector correlation      — ≤ 2 positions in same sector
│
Playbook completeness   — if BUY+new-entry: evidence has ≥ 3 bullets
```

Rejected → `rejections.append((decision, reason))`. Never persisted.
Logged to Telegram.

### 9.2 Simulator (`portfolio/simulator.py`)

Price + time semantics:
- **Fill**: `fill_price = ohlc.open (ATO)` của ngày `expected_fill_date`.
  Open không có → order stays pending (day after day).
- **Fee BUY**: `qty * fill_price * FEE_BUY_BPS / 10000`.
- **Fee SELL**: `qty * fill_price * FEE_SELL_BPS / 10000` (gồm thuế TNCN
  0.1% VN).
- **Stop-loss check** on EOD: if `close / avg_cost - 1 < -0.08` → emit
  SELL with `playbook=cut-loser`. Goes through validator + simulator như
  Claude's proposal.

T+2 tracking:
- `holdings.qty_available` — shares eligible to SELL today.
- `holdings.qty_total` — all shares (including locked).
- On BUY fill: `qty_total += qty`. `qty_available` doesn't change today
  + next day.
- `release_t2_shares(today)` bumps `qty_available` cho shares mua cách
  đây ≥ 2 trading days.

All money **int VND**. Never float. `telegram/format.py::format_vnd`
renders for display only.

---

## 10. Bias detection

### 10.1 Formulas

Per PLAN_V2 §5.4 + Vibe-Trading calibration:

| Bias | Formula | Medium | High |
|---|---|---|---|
| **Disposition effect** | `avg_loser_hold_days / avg_winner_hold_days` | ≥ 1.2 | ≥ 1.5 |
| **Overtrading** | `(quiet_day_avg_pnl - busy_day_avg_pnl) / \|quiet\|`<br>quiet = ≤2 trades/day, busy = ≥4 | ≥ 0.3 | ≥ 1.0 |
| **Chase momentum** | `% buys with price ≥ min(prior_20_buys) × 1.03` | ≥ 40% | ≥ 60% |
| **Anchoring** | `% tickers (≥5 buys) with entry-price CV < 5%` | ≥ 33% | ≥ 66% |
| **Hot hand sizing** | `Pearson corr(prev_sell_was_win, next_buy_pct_nav)` | ≥ 0.4 | ≥ 0.6 |
| **Skill dogma** | `% decisions using top-1 skill` | ≥ 55% | ≥ 70% |
| **Recency** | `% thesis containing "tuần trước/hôm qua/…"` | ≥ 30% | ≥ 40% |

### 10.2 Insufficient data handling

Every detector has a minimum sample threshold. If below:
```python
return BiasResult(severity="low", metric=0.0, sample_size=n,
                  evidence="insufficient data (winners=X, losers=Y)")
```

The grid always has 7 rows even on empty DB — callers don't need to
special-case.

### 10.3 When it fires

- **Weekly cron**: `run_bot_bias_check(persist=True)` → UPSERT bias_reports.
- **On-demand**: `/bias` Telegram → `run_bot_bias_check(persist=False)`.
- **Shadow Account**: `analyze_trade_journal` returns 7 results (on user
  trades, not bot decisions) to render section 2 of HTML report.

### 10.4 Bias flags on individual decisions (future)

Schema has `decisions.bias_flags_json` but no writer wires it yet.
Intended path: `orchestrator/new_entry_debate` PM node runs detectors
on the candidate decision + flags. Currently detectors are batch-only.

---

## 11. Observability

### 11.1 Structured logs (`logging_setup.py`)
- `structlog` → JSON lines → `logs/vnstock-bot.log`.
- Rotate 7 days.
- Key events: `boot`, `scheduler_started`, `daily_job_start`,
  `daily_job_done`, `daily_job_failed`, `weekly_job_failed`,
  `dag_done`, `skill_stats_computed`, `patterns_extracted`,
  `shadow_upload_failed`.

### 11.2 Heartbeats
- Daily: `"✅ daily_research OK — 3 decisions, 0 rejected, 12s, ~15k tokens"`
  or `"❌ daily_research FAILED: vnstock.timeout ..."`.
- Weekly: summary với stats/bias/lifecycle/proposer.
- Boot: `"🤖 vnstock-bot online"`.

### 11.3 Traces
- Every swarm DAG run → `trace_id` UUID.
- Persisted `dag_traces` + `dag_node_results`.
- Decisions coming out of swarm have `decisions.trace_id` linked.
- Replay via `/why <trace_id>` or `/why d<decision_id>`.

### 11.4 Memory events
- Every L1 event has `created_at, kind, ticker, decision_id, trace_id,
  summary, payload_json`.
- FTS5 indexed for search.
- `events_fts` has `UNINDEXED` columns for filter-without-search.

---

## 12. Failure modes & fallbacks

### 12.1 Claude SDK unauth
- Symptom: `run_agent` throws on first `ClaudeSDKClient` init.
- Fallback: daily job catches exception → Telegram error + DB heartbeat.
  Orders pending from yesterday still fill, stop-loss auto-proposals still
  fire (they don't need Claude).
- Fix: `claude login` locally.

### 12.2 vnstock timeout / rate limit
- Symptom: `data/vnstock_client.fetch_ohlc` returns empty OR throws.
- Fallback: `ohlc_cache` table. Warm-cache ahead of time via
  `vnstock-bot warm-cache --days 90`.
- On daily: snapshot gets built from cache; daily research can still emit
  HOLD decisions based on cached data.

### 12.3 DAG node failure
- `orchestrator/dag.py` wraps each node in `asyncio.wait_for` + try/except.
- Fail → status `failed` or `timeout`, downstream nodes marked `skipped`.
- DAG status rolls up: all success = `success`; some success = `partial`;
  none = `failed`.
- Partial DAGs still emit useful output (what succeeded).

### 12.4 DAG runner timeout
- Outer `wait_for(spec.timeout_seconds)` kills runaway DAGs.
- Unfinished nodes marked `timeout`.
- Telegram heartbeat shows which nodes completed.

### 12.5 Swarm path fails, need to fall back
- No automatic fallback — if `DAILY_RESEARCH_MODE=swarm` and DAG fails,
  the day's decisions are missed.
- Manual recovery: flip env to `single`, run `vnstock-bot today`.

### 12.6 FTS5 corruption
- Symptom: `fts5.search` raises `sqlite3.DatabaseError`.
- `fts5.fts5_available()` returns False.
- Recovery: `fts5.rebuild_index()` — DELETEs + reinserts from events table.
  L1 events are authoritative; FTS5 is always rebuildable.

### 12.7 Skill file frontmatter missing
- `skill_lifecycle._bump_frontmatter_status` raises `ValueError`.
- `apply_decision` catches? No — it lets it propagate. Result: transition
  skipped for that skill, weekly review continues.
- Fix: add frontmatter manually + rerun weekly.

### 12.8 Broker CSV parse failure
- `on_document` catches exception → Telegram `"❌ Parse thất bại: <err>"`.
- File saved to `data/shadow/<ts>_<filename>.csv` regardless — user can
  inspect + fix.

### 12.9 Weekly review mid-step failure
- Each step is independent except lifecycle-after-stats ordering.
- If step N fails, prior steps already committed (DB transactions per
  operation, not per job).
- Exception in top-level handler → Telegram error + DB heartbeat.

---

## 13. Troubleshooting quick-ref

| Symptom | Likely cause | Check |
|---|---|---|
| `/today` returns empty | Claude SDK unauth | `vnstock-bot doctor` |
| Bot doesn't reply | Chat ID not whitelisted | `logs/vnstock-bot.log` for incoming `chat_id` |
| Skill stuck at shadow forever | < 30 scored decisions OR ci_low < 0.5 | `SELECT * FROM skill_scores_v2 WHERE skill=?` |
| `/debate` hangs | Claude SDK slow OR node timeout | `/why <trace_id>` after |
| `/shadow upload` fails | Unknown broker format | Send plain `generic` CSV (date,ticker,side,qty,price) |
| Daily double-fills | Idempotency broken | `SELECT * FROM daily_equity WHERE date=?` — should be unique |
| Decision no `trace_id` | Came from `single` path | Normal — v1 single-agent doesn't set trace_id |
| `/bias` shows 7 × low | < 90d history OR no filled orders | `SELECT count(*) FROM orders WHERE status='filled'` |
| Empty `/regime` | No `macro_sector_desk` run | Trigger via swarm cron or manual `run_preset` |
| Weekly ran but no lifecycle changes | No skill hit stat gate | Check `skill_scores_v2.ci_low` + `wf_pass_count` |
| Pine export missing file | `data/export/pine/` write perm | Check `ls -la data/export/pine/` |
| MCP server silent | Stdin empty or malformed JSON | Test with `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \| vnstock-bot-mcp` |

---

## Appendix: key env knobs

Defaults in `config.py`. Override via `.env`.

| Env | Default | Impact |
|---|---|---|
| `DAILY_RESEARCH_MODE` | `single` | Swarm DAG vs single-agent for cron 15:30 |
| `TELEGRAM_CHAT_ID_WHITELIST` | (none) | Comma-sep chat IDs allowed |
| `INITIAL_CAPITAL_VND` | `100000000` | Starting NAV for simulator |
| `FEE_BUY_BPS` | `15` | 0.15% — adjust for broker |
| `FEE_SELL_BPS` | `25` | 0.25% (incl. tax) |
| `DAILY_CRON_HOUR`/`MINUTE` | `15`/`30` | When daily fires |
| `WEEKLY_CRON_DAY`/`HOUR` | `sun`/`10` | When weekly fires |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude Agent SDK model |
| `CLAUDE_MAX_TURNS` | `20` | Per-agent turn limit |
| `CLAUDE_DAILY_TOKEN_BUDGET` | `40000` | Soft budget warning |
| `LOG_LEVEL` | `INFO` | structlog level |
| `TZ` | `Asia/Ho_Chi_Minh` | APScheduler timezone |
| `MEMORY_DIR` | `data/memory` | L2/L4 file memory root |
