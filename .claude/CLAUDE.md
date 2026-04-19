# CLAUDE.md — vnstock-bot

Project-level guidance for Claude Code when working on this repo.

## Context

- Personal Telegram bot, 1 user, runs local on macOS.
- Vietnamese stock market simulator + advisor.
- Uses Claude Agent SDK (Max subscription auth, no API key).
- **Two versions coexist:**
  - **v1** — current implemented: single-agent research, 7 skills, weekly review.
  - **v2** — under construction: swarm DAG (6 preset), 25-30 skills port từ
    Vibe-Trading, 5-layer FTS5 memory, Shadow Account, 7 bias detector,
    bootstrap CI + walk-forward, Pine Script export, MCP server.
- Primary references: [PLAN.md](../PLAN.md), [PLAN_V2.md](../PLAN_V2.md),
  [ARCHITECTURE.md](../ARCHITECTURE.md).
- **When implementing v2:** check PLAN_V2 for target design, ARCHITECTURE §V2
  for topology + module status table. Update status `📋 planned` → `✅ done`
  in ARCHITECTURE after implement + tests pass.

## Golden rules

1. **Money is `int` VND.** No `float` in simulator, DB, validator, or portfolio.
2. **Timezone: `Asia/Ho_Chi_Minh`.** All datetimes aware. Use `data/holidays.now_vn()`.
3. **No lookahead.** Research agent sees data only up to today's close; orders
   fill at T+1 ATO.
4. **T+2 settlement.** Respect `qty_available` vs `qty_total`.
5. **Validate before persist.** Every Claude-proposed decision must pass
   `portfolio/validator.py` before reaching DB.
6. **Skills are rule-book, not lore.** Each skill file has frontmatter + clear
   rules. Evidence must cite numbers. Weekly review may edit skills, but ≤ 2
   per week and always via git commit.

## Boundaries

### v1 (always apply)

- `research/` is the only module that imports `claude_agent_sdk`.
- `db/queries.py` is the only module issuing SQL; everything else goes through
  typed helpers.
- `telegram/` never imports `portfolio/simulator` directly — go through
  `portfolio/reporter` for rendered output.
- Keep money conversions (VND ↔ display string) in `telegram/format.py`.

### v2 (apply when touching v2 modules)

- `orchestrator/` is the only module that runs multi-agent DAG. Single-agent
  fallback stays in `research/agent.py`. Do NOT call DAG runner from
  `telegram/` directly — route through `orchestrator`.
- `memory/` owns all reads/writes to `~/.vnstock-bot/memory/*.md` and the
  `events_fts` table. Other modules import `search_memory`, `recall_similar`,
  `write_memory` — never open markdown memory files directly.
- `shadow/` parses broker CSV only through `shadow/parsers/*`. Never parse
  inside `telegram/` or `research/`.
- `bias/` is pure: `list[Decision] → list[BiasFlag]`. No DB writes, no
  persistence.
- `learning/stats.py` is the only place allowed to import `scipy.stats` /
  `arch`. Skill lifecycle transitions (`learning/skill_lifecycle.py`) must
  not skip the stat gate.
- `mcp/server.py` exposes READ-ONLY tools only: `get_price`,
  `get_portfolio`, `search_memory`, `get_timeline`, `recall_similar_decision`.
  NEVER expose `propose_trade`, `write_skill`, or any file-write tool.
- DuckDB `ATTACH` SQLite in read-only mode only. Views live in
  `db/duckdb_views.sql`. No parallel writes.

### Invariants added in v2

- **Statistical gate for skill promotion:** draft → shadow → active only
  via `learning/skill_lifecycle.py`. Gate: ≥30 uses AND `ci95_low > 0.5` AND
  walk-forward pass ≥3/5 windows AND beat parent ≥2% absolute win-rate.
- **DAG replay determinism:** `trace_id` + seed + cached market data must
  reproduce identical output.
- **Bias flags are advisory, not blocking.** `bias_flags` on a Decision
  log + display only. Do NOT auto-reject based on bias. Calibrate via
  weekly review.
- **Shadow skills are log-only.** A shadow skill never creates pending
  orders; it runs parallel to the active skill and compares outcomes only.

## Coding style

- Python 3.12, type hints everywhere.
- Pydantic v2 for all external-boundary data (Claude output, config, API results).
- `dataclass` for internal domain types.
- `structlog` for logging. No `print` except CLI output.
- Tests colocated under `tests/`, mirror `src/` structure.
- Don't add docstrings on obvious functions. Only comment non-obvious "why".
- Keep files under ~400 lines; split if larger.

## Don'ts

- Don't introduce ORM (SQLAlchemy) or migration lib (Alembic). Schema is
  hand-managed via `db/schema.sql`.
- Don't add `ANTHROPIC_API_KEY` — we use Claude CLI session auth.
- Don't fetch vnstock inside hot paths without caching.
- Don't write tests that hit real network by default.

## When Claude modifies skills

- Must preserve frontmatter (`name`, `when_to_use`, `inputs`, `outputs`, `version`).
- Bump `version` on rule change.
- Keep each rule numbered, testable, with objective criteria.
- If deleting a rule, move it to a `## Deprecated rules` section (don't silently drop).

### v2 skill frontmatter (when implementing skill lifecycle)

Skill files in v2 add these fields:

```yaml
status: active          # draft | shadow | active | archived
category: analysis      # analysis | strategy | risk | flow | tool
parent_skill: null      # filled when forked
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null    # [low, high] from bootstrap
walk_forward_stable: null
shadow_vs_parent: null  # absolute win-rate delta
```

- New skill starts in `status: draft`. Human `/skill promote <name>` moves
  it to `shadow`. Lifecycle FSM promotes shadow → active only if stat gate
  passes (see invariants above).
- `skill_proposer` agent may create drafts during weekly review (≤2/week).
- Never hand-edit the stat fields — those are populated by
  `learning/skill_scorer.py` + `learning/stats.py`.

## When implementing v2 modules

1. Read [PLAN_V2.md](../PLAN_V2.md) section for that module first — the
   thresholds (bias Medium/High, skill gate, 15 backtest metrics, 4 bias
   formulas) are intentional and sourced from Vibe-Trading.
2. Preserve v1 behavior. v2 adds, does not replace v1 paths until explicitly
   retired (e.g., single-agent `research/agent.py` stays as DAG fallback).
3. Add tests in `tests/` mirroring the `src/` path. Statistical code
   (bootstrap, walk-forward) needs fixture with known expected CI.
4. After module done, update ARCHITECTURE.md "V2 Files cheat sheet" status
   `📋 planned` → `✅ done` in the same PR.
