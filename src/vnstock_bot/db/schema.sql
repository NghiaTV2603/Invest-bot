-- vnstock-bot schema. Source of truth; hand-managed (no Alembic).
-- All money stored as INTEGER VND.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Portfolio state
CREATE TABLE IF NOT EXISTS holdings (
    ticker TEXT PRIMARY KEY,
    qty_total INTEGER NOT NULL,
    qty_available INTEGER NOT NULL,
    avg_cost INTEGER NOT NULL,            -- VND/cp
    opened_at TEXT NOT NULL,              -- ISO date
    last_buy_at TEXT                      -- ISO date, for T+2 counter
);

-- Claude's proposals (both filled and pending)
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('BUY','ADD','TRIM','SELL','HOLD')),
    qty INTEGER NOT NULL,
    target_price INTEGER,
    stop_loss INTEGER,
    thesis TEXT NOT NULL,
    evidence_json TEXT NOT NULL,          -- JSON list[str]
    risks_json TEXT NOT NULL,             -- JSON list[str]
    invalidation TEXT NOT NULL,
    skills_used_json TEXT NOT NULL,       -- JSON list[str]
    playbook TEXT,
    conviction INTEGER NOT NULL CHECK (conviction BETWEEN 1 AND 5),
    source TEXT NOT NULL CHECK (source IN ('claude_daily','claude_chat','user_manual','simulator_auto')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','filled','cancelled','rejected')),
    rejection_reason TEXT,
    -- v2: link decision to DAG trace for /why replay. NULL for v1 decisions.
    trace_id TEXT,
    -- v2: 3-scenario targets (Vibe-Trading pattern). NULL for v1.
    target_bear INTEGER,
    target_base INTEGER,
    target_bull INTEGER,
    -- v2: bias flags detected at decision time. JSON list[str]. NULL for v1.
    bias_flags_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_trace ON decisions(trace_id);

-- Orders derived from decisions (simulator fills them)
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decisions(id),
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    qty INTEGER NOT NULL,
    placed_at TEXT NOT NULL,              -- ISO date (decision day)
    expected_fill_date TEXT NOT NULL,     -- ISO date (next trading day)
    filled_at TEXT,
    fill_price INTEGER,
    fee INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','filled','cancelled','failed'))
);

-- Daily equity snapshot
CREATE TABLE IF NOT EXISTS daily_equity (
    date TEXT PRIMARY KEY,                -- ISO date
    cash INTEGER NOT NULL,
    market_value INTEGER NOT NULL,
    total INTEGER NOT NULL,
    vnindex REAL,
    notes TEXT
);

-- Market-wide snapshot
CREATE TABLE IF NOT EXISTS market_snapshot (
    date TEXT PRIMARY KEY,
    vnindex_open REAL,
    vnindex_high REAL,
    vnindex_low REAL,
    vnindex_close REAL,
    vnindex_volume INTEGER,
    foreign_buy INTEGER,                  -- VND
    foreign_sell INTEGER,                 -- VND
    top_movers_json TEXT                  -- JSON
);

-- Skills performance (learning loop)
CREATE TABLE IF NOT EXISTS skill_scores (
    skill TEXT PRIMARY KEY,
    uses INTEGER NOT NULL DEFAULT 0,
    wins_5d INTEGER NOT NULL DEFAULT 0,
    wins_20d INTEGER NOT NULL DEFAULT 0,
    last_used TEXT
);

-- Decision outcomes (scored after N days)
CREATE TABLE IF NOT EXISTS decision_outcomes (
    decision_id INTEGER NOT NULL REFERENCES decisions(id),
    days_held INTEGER NOT NULL,
    pnl_pct REAL,
    thesis_valid INTEGER,                 -- 1/0
    invalidation_hit INTEGER,             -- 1/0
    scored_at TEXT NOT NULL,
    PRIMARY KEY (decision_id, days_held)
);

-- Chat history (telegram)
CREATE TABLE IF NOT EXISTS chat_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user','assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- OHLC cache (avoid re-hitting vnstock)
CREATE TABLE IF NOT EXISTS ohlc_cache (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    open INTEGER,
    high INTEGER,
    low INTEGER,
    close INTEGER,
    volume INTEGER,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON decisions(ticker);
CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_expected_fill ON orders(expected_fill_date);
CREATE INDEX IF NOT EXISTS idx_ohlc_ticker_date ON ohlc_cache(ticker, date);
CREATE INDEX IF NOT EXISTS idx_chat_history_chat ON chat_history(chat_id, created_at);

-- ============================================================
-- V2: Memory layer (L1 events, L3 summaries, L4 patterns)
-- See PLAN_V2.md §4.
-- ============================================================

-- L1: raw event log (chat, decision, tool_call, note, observation)
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,                    -- ISO datetime (Asia/Ho_Chi_Minh)
    kind TEXT NOT NULL CHECK (kind IN ('chat','decision','tool_call','note','observation')),
    ticker TEXT,                                 -- nullable; some events aren't ticker-scoped
    decision_id INTEGER REFERENCES decisions(id),
    trace_id TEXT,                               -- UUID for DAG replay (v2)
    summary TEXT NOT NULL,                       -- short human-readable (ranked 2x in FTS5)
    payload_json TEXT NOT NULL                   -- full structured payload
);

CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_ticker ON events(ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events(trace_id);

-- FTS5 index over events. 'unicode61 remove_diacritics 2' handles Vietnamese
-- by stripping diacritics + case folding: "mở" → "mo", "HOẠT" → "hoat".
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    summary,
    payload_text,
    ticker UNINDEXED,
    kind UNINDEXED,
    event_id UNINDEXED,
    created_at UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2"
);

-- L3: compressed summaries (daily / weekly / per-ticker snapshots)
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    scope TEXT NOT NULL CHECK (scope IN ('daily','weekly','ticker','session')),
    key TEXT NOT NULL,                           -- date ISO / ticker / session_id
    body TEXT NOT NULL,                          -- markdown text
    event_count INTEGER NOT NULL DEFAULT 0,      -- how many L1 events compressed
    UNIQUE (scope, key)
);

CREATE INDEX IF NOT EXISTS idx_summaries_scope_key ON summaries(scope, key);

-- L4: extracted patterns from observations ("5/7 winners had vol > 2x MA20")
-- Patterns age out (TTL 90d unless confirmed=1).
CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL,
    support_count INTEGER NOT NULL DEFAULT 0,
    confirmed INTEGER NOT NULL DEFAULT 0,        -- 1 = promoted to skill or L5
    last_seen_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_patterns_last_seen ON patterns(last_seen_at);

-- ============================================================
-- V2: DAG orchestrator trace log. See PLAN_V2.md §3, §11.
-- Every swarm preset run creates one row here + one row per node.
-- ============================================================

CREATE TABLE IF NOT EXISTS dag_traces (
    trace_id TEXT PRIMARY KEY,
    preset TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending','running','success','failed','timeout','partial'
    )),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    elapsed_ms INTEGER,
    variables_json TEXT NOT NULL DEFAULT '{}',
    final_output_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_dag_traces_preset ON dag_traces(preset, started_at);
CREATE INDEX IF NOT EXISTS idx_dag_traces_status ON dag_traces(status);

CREATE TABLE IF NOT EXISTS dag_node_results (
    trace_id TEXT NOT NULL REFERENCES dag_traces(trace_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending','running','success','failed','timeout','skipped'
    )),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    elapsed_ms INTEGER,
    output_json TEXT,
    error TEXT,
    PRIMARY KEY (trace_id, node_id)
);

-- ============================================================
-- V2 W4: Statistical skill scores + bias reports + lifecycle audit.
-- See PLAN_V2.md §2.3 (skill lifecycle), §5.4 (bias formulas), §6 (stats).
-- ============================================================

-- Statistical skill scores (replaces v1 skill_scores for v2 decisions).
-- v1 skill_scores kept untouched for backward compat.
CREATE TABLE IF NOT EXISTS skill_scores_v2 (
    skill TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('draft','shadow','active','archived')),
    parent_skill TEXT,
    uses INTEGER NOT NULL DEFAULT 0,
    trades_with_signal INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    win_rate_point REAL,             -- simple point estimate
    win_rate_ci_low REAL,            -- bootstrap 95% CI
    win_rate_ci_high REAL,
    mc_pvalue REAL,                  -- Monte Carlo permutation p-value
    wf_pass_count INTEGER,           -- walk-forward windows with Sharpe > 0
    wf_total_windows INTEGER DEFAULT 5,
    shadow_vs_parent REAL,           -- % absolute win-rate delta (shadow vs parent)
    last_computed_at TEXT,
    last_used_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_skill_scores_v2_status ON skill_scores_v2(status);

-- Bias diagnostic reports (weekly rollup).
-- scope = 'bot' for bot's own decisions; 'user_shadow_<id>' for shadow account.
CREATE TABLE IF NOT EXISTS bias_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    week_of TEXT NOT NULL,
    bias_name TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low','medium','high')),
    metric REAL NOT NULL,
    threshold_medium REAL NOT NULL,
    threshold_high REAL NOT NULL,
    evidence TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (scope, week_of, bias_name)
);

CREATE INDEX IF NOT EXISTS idx_bias_reports_scope_week ON bias_reports(scope, week_of);

-- Audit log of skill status transitions (draft→shadow→active→archived).
CREATE TABLE IF NOT EXISTS skill_lifecycle_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    skill TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lifecycle_skill ON skill_lifecycle_transitions(skill, created_at);

-- ============================================================
-- V2 W5: Shadow Account — user upload broker CSV → rules + Delta-PnL.
-- See PLAN_V2.md §5.
-- ============================================================

CREATE TABLE IF NOT EXISTS shadow_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT UNIQUE NOT NULL,          -- external reference (UUID)
    broker TEXT,                             -- 'ssi' | 'vps' | 'tcbs' | 'mbs' | 'generic'
    journal_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    total_trades INTEGER NOT NULL DEFAULT 0,
    roundtrips INTEGER NOT NULL DEFAULT 0,
    start_date TEXT,
    end_date TEXT,
    real_pnl INTEGER NOT NULL DEFAULT 0,     -- VND int
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_shadow_accounts_uploaded ON shadow_accounts(uploaded_at);

CREATE TABLE IF NOT EXISTS shadow_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL REFERENCES shadow_accounts(shadow_id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,                   -- stable ID within shadow (e.g. 'rule-1')
    human_text TEXT NOT NULL,                -- ≤ 30 chars per PLAN_V2
    support_count INTEGER NOT NULL,
    coverage_rate REAL NOT NULL,
    sector TEXT,
    hour_bucket TEXT,                        -- '09:15-10:00' | '10:00-11:00' | ...
    holding_min INTEGER,
    holding_max INTEGER,
    win_rate REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (shadow_id, rule_id)
);

CREATE TABLE IF NOT EXISTS shadow_backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shadow_id TEXT NOT NULL REFERENCES shadow_accounts(shadow_id) ON DELETE CASCADE,
    run_at TEXT NOT NULL,
    real_pnl INTEGER NOT NULL,
    shadow_pnl INTEGER NOT NULL,
    delta_pnl INTEGER NOT NULL,              -- shadow - real (positive = shadow better)
    noise_trades_pnl INTEGER NOT NULL DEFAULT 0,
    early_exit_pnl INTEGER NOT NULL DEFAULT 0,
    late_exit_pnl INTEGER NOT NULL DEFAULT 0,
    overtrading_pnl INTEGER NOT NULL DEFAULT 0,
    missed_signals_pnl INTEGER NOT NULL DEFAULT 0,
    report_html_path TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_shadow_backtests_run_at ON shadow_backtests(run_at);
