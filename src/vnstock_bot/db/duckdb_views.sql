-- DuckDB analytics views for vnstock-bot v2 (PLAN_V2 §8, ARCHITECTURE).
--
-- Usage:
--   duckdb /path/to/analytics.duckdb
--   ATTACH '/path/to/bot.db' (TYPE sqlite, READ_ONLY);
--   .read src/vnstock_bot/db/duckdb_views.sql
--
-- Views expose read-only analytics over the SQLite operational DB.
-- DuckDB is NOT a hard dep — v2 works without it, but these views power
-- faster rolling-window stats + ad-hoc analysis.

-- Drop old versions if present (for re-runs)
DROP VIEW IF EXISTS v_equity_rolling;
DROP VIEW IF EXISTS v_skill_ci;
DROP VIEW IF EXISTS v_decision_attrib;
DROP VIEW IF EXISTS v_regime_labels;

-- ============================================================
-- v_equity_rolling: rolling Sharpe + drawdown over 20/60/252 windows.
-- ============================================================
CREATE VIEW v_equity_rolling AS
SELECT
    date,
    total,
    total - LAG(total) OVER (ORDER BY date) AS daily_pnl,
    (total / LAG(total) OVER (ORDER BY date)) - 1 AS daily_return,
    AVG((total - LAG(total) OVER (ORDER BY date)) * 1.0 / LAG(total) OVER (ORDER BY date))
        OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        AS mean_ret_20d,
    STDDEV_SAMP((total - LAG(total) OVER (ORDER BY date)) * 1.0 / LAG(total) OVER (ORDER BY date))
        OVER (ORDER BY date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
        AS std_ret_20d,
    MAX(total) OVER (ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
        AS peak_60d,
    total * 1.0 / MAX(total) OVER (ORDER BY date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW) - 1
        AS drawdown_60d,
    vnindex
FROM sqlite.daily_equity;


-- ============================================================
-- v_skill_ci: latest statistical scores per skill (from skill_scores_v2).
-- Joined with lifecycle transitions to show last status change.
-- ============================================================
CREATE VIEW v_skill_ci AS
SELECT
    s.skill,
    s.status,
    s.uses,
    s.trades_with_signal,
    s.wins,
    s.losses,
    s.win_rate_point,
    s.win_rate_ci_low,
    s.win_rate_ci_high,
    s.mc_pvalue,
    s.wf_pass_count,
    s.wf_total_windows,
    (s.wf_pass_count * 1.0 / NULLIF(s.wf_total_windows, 0)) AS wf_pass_ratio,
    s.parent_skill,
    s.shadow_vs_parent,
    s.last_computed_at,
    (SELECT MAX(lt.created_at) FROM sqlite.skill_lifecycle_transitions lt
      WHERE lt.skill = s.skill) AS last_transition_at
FROM sqlite.skill_scores_v2 s;


-- ============================================================
-- v_decision_attrib: per-decision P&L + skills used + outcome.
-- ============================================================
CREATE VIEW v_decision_attrib AS
SELECT
    d.id AS decision_id,
    d.created_at,
    d.ticker,
    d.action,
    d.conviction,
    d.playbook,
    d.skills_used_json,
    d.source,
    d.status,
    o.filled_at,
    o.fill_price,
    (SELECT MAX(do_.pnl_pct) FROM sqlite.decision_outcomes do_
      WHERE do_.decision_id = d.id) AS latest_pnl_pct,
    (SELECT MAX(do_.invalidation_hit) FROM sqlite.decision_outcomes do_
      WHERE do_.decision_id = d.id) AS invalidation_hit,
    (SELECT MAX(do_.thesis_valid) FROM sqlite.decision_outcomes do_
      WHERE do_.decision_id = d.id) AS thesis_valid
FROM sqlite.decisions d
LEFT JOIN sqlite.orders o ON o.decision_id = d.id;


-- ============================================================
-- v_regime_labels: timeline of regime labels from dag_traces (macro_sector_desk).
-- ============================================================
CREATE VIEW v_regime_labels AS
SELECT
    trace_id,
    preset,
    started_at,
    ended_at,
    elapsed_ms,
    status,
    final_output_json
FROM sqlite.dag_traces
WHERE preset = 'macro_sector_desk'
  AND status = 'success'
ORDER BY started_at DESC;
