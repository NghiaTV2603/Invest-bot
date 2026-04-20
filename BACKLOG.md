# Backlog — vnstock-bot

Danh sách những gì có thể làm tiếp. Xếp theo **priority** + **estimate**
thực tế cho 1 dev làm part-time. Nhặt từ trên xuống; mỗi item có tiêu
chí "done when" cụ thể.

> Status ghi chú: 📋 chưa làm • 🏃 đang làm • ✅ done • ❌ won't do
> (kèm lý do)

---

## P0 — Bug fix + quality wins (đáng làm trước, 0.5-1 ngày mỗi cái)

### 📋 BUG-1 Test residue: `skills/strategy/lc_*.md` cứ xuất hiện sau mỗi `pytest`
- **Nguyên nhân:** `test_skill_lifecycle.py` + `test_skill_stats_compute.py`
  gọi `write_skill()` ghi vào real `skills/` dir vì conftest chưa
  override `SKILLS_DIR`.
- **Scope:** thêm `skills_dir: Path` vào `Settings` (giống `memory_dir`),
  fallback env `SKILLS_DIR`, update conftest `monkeypatch.setenv`, update
  `skill_loader.read_skill` + `write_skill` dùng `get_settings().skills_dir`.
- **Done when:** Chạy `pytest` 10 lần, `skills/strategy/lc_*.md` không
  còn xuất hiện. Tests vẫn 218/218 pass.

### 📋 BUG-2 vnstock `tcbs` module import fail cho MWG / MSN fundamentals
- **Nguyên nhân:** `from vnstock.explorer.tcbs import ...` — version vnstock
  hiện tại không có submodule này.
- **Scope:** `uv add vnstock --upgrade` OR switch sang VCI-only trong
  `vnstock_client.fetch_fundamentals` + fallback stub nếu cả 2 fail.
- **Done when:** `uv run vnstock-bot doctor` + `/today` không còn warning
  `fundamentals_fetch_failed` cho MWG/MSN. Test coverage: mock both
  providers fail → return empty dict gracefully.

### 📋 BUG-3 Pre-existing ruff warnings (v1 code)
- `src/vnstock_bot/db/queries.py:227` — `l` ambiguous var name trong
  `upsert_ohlc(o, h, l, c, v)`. Rename `l` → `low` + update callsites.
- `src/vnstock_bot/scheduler/jobs.py:89` — `settings = get_settings()`
  unused trong `daily_research_single_job`. Xóa 1 dòng.
- **Done when:** `uv run ruff check src tests` returns clean (0 errors).

### 📋 QUAL-1 CI pipeline — GitHub Actions
- **Scope:** `.github/workflows/test.yml` chạy `uv sync` + `uv run pytest` +
  `uv run ruff check src tests` on push/PR. Matrix Python 3.12 only.
- **Done when:** Badge pass trên README, PR block khi test fail.

### 📋 QUAL-2 Pre-commit hook
- **Scope:** `.pre-commit-config.yaml` với `ruff check --fix` + `ruff
  format`. Thêm `pre-commit install` vào README setup.
- **Done when:** Commit có code lỗi → bị hook block trước khi push.

### 📋 POLISH-1 Fix flaky date-based tests khác
- `test_queries.py::test_decision_insert_and_recent` đã fix.
- Check toàn bộ `tests/` còn test nào hardcode `2026-04-XX` không —
  đổi sang `now_vn()` hoặc `freezegun`.
- **Done when:** `grep -r "2026-04-" tests/` chỉ còn trong comments hoặc
  fixture metadata.

---

## P1 — Feature polish + wire-up còn thiếu (1-3 ngày mỗi cái)

### 📋 WIRE-1 Decision `bias_flags_json` writer
- **Schema đã có, writer chưa.** PM node trong `new_entry_debate` swarm
  nên chạy `bias.detectors.detect_all` trên candidate decision + persist
  `bias_flags` khi gọi `insert_decision`.
- **Scope:** Extend `orchestrator/builtins.py` PM node OR wrap
  `propose_trade` tool để detect + pass through.
- **Done when:** `SELECT count(*) FROM decisions WHERE bias_flags_json IS
  NOT NULL` > 0 sau vài `/debate` runs. Chat `/why d42` hiển thị bias flags.

### 📋 WIRE-2 L3 summaries auto-writer
- **Schema `summaries` table có, writer chưa.**
- **Scope:** Thêm step cuối daily_research_job + weekly_review_job:
  compact events L1 của ngày/tuần thành 1 summary row (scope='daily'/'weekly',
  key=date). `memory/compression.py` đã có logic đọc — giờ cần logic ghi.
- **Done when:** Sau 1 tuần cron chạy, `SELECT * FROM summaries` có ≥ 5
  daily rows + 1 weekly row. `compress_context` có content L3 thực sự
  thay vì empty.

### 📋 WIRE-3 DuckDB views auto-refresh
- **File `duckdb_views.sql` có, chưa integrate.**
- **Scope:** Weekly job chạy `duckdb data/bot.duckdb < duckdb_views.sql`
  sau khi SQLite state settle. Expose helper `analytics.load_equity_rolling()`
  dùng được trong Python.
- **Done when:** `/report` command pull từ `v_equity_rolling` thay vì tự
  tính daily. Telegram render biểu đồ rolling Sharpe 20d.

### 📋 FEAT-1 Excel export decisions (cho tax report)
- **Why:** Cuối năm user cần report PnL cho thuế TNCN. Bot đã track mọi
  fill → có thể auto-generate.
- **Scope:** `/export excel` command → openpyxl workbook với 3 sheet
  (decisions, orders, daily_equity). Output `data/export/excel/<date>.xlsx`.
- **Done when:** File Excel mở được, columns formatted, tổng PnL khớp
  `daily_equity.total - INITIAL_CAPITAL_VND`.

### 📋 FEAT-2 Morning pre-market briefing (7:30 sáng)
- **Why:** User muốn biết thị trường hôm nay trước 9:15 ATO mở.
- **Scope:** Cron mới 7:30 thứ 2-6 → fetch overnight US market (SPY, DJI,
  nếu có), giá dầu, tin tức VN overnight (RSS CafeF), holdings T+2 release
  → render brief Telegram.
- **Done when:** Mỗi sáng thứ 2-6 có tin nhắn ngắn ≤ 15 dòng với US
  overnight + top 3 Vietnamese news headline + portfolio status.

### 📋 FEAT-3 Backtest equity curve HTML plot
- **Why:** `/backtest 6` hiện chỉ trả số. User muốn thấy equity curve vs
  VN-Index.
- **Scope:** Sau khi `run_backtest` xong, render SVG equity curve (inline,
  no matplotlib dep — giống shadow report) + save HTML at
  `data/backtest/<run_id>/report.html`. Telegram reply kèm path.
- **Done when:** File HTML mở trong browser thấy 2 đường (strategy +
  VN-Index) + metric summary table. Dev có thể compare runs visually.

### 📋 INFRA-1 Docker packaging
- **Scope:** `Dockerfile` + `docker-compose.yml`. Mount volume cho
  `data/` + `logs/` + `skills/` + `.env`. Entrypoint `vnstock-bot run`.
- **Done when:** `docker compose up -d` chạy bot với cùng state như
  native run. Healthcheck probe `/doctor`.

### 📋 DOC-1 Deploy guide
- **Scope:** `DEPLOY.md` — 3 option: tmux (dev), systemd (linux server),
  launchd (macOS). Backup/restore cho `data/bot.db`. Log rotation policy.
- **Done when:** User mới đọc + deploy được trong 30 phút.

---

## P2 — Substantial features (3-7 ngày)

### 📋 FEAT-4 WeasyPrint PDF cho Shadow Account report
- **Scope:** Fallback optional dep. Nếu có cairo/pango → generate PDF song
  song HTML. Nếu không → skip + note "install cairo + pango for PDF".
- **Dependencies:** `weasyprint` optional dep in pyproject.
- **Done when:** `render_shadow_report(..., pdf=True)` output cả `.html`
  + `.pdf`. PDF có chart vector, page break hợp lý.

### 📋 FEAT-5 MBS broker parser
- **Blocked on:** Cần CSV sample thật từ MBS (user chưa có).
- **Scope:** `shadow/parsers/mbs.py` + detect logic + test fixture.
- **Done when:** Upload CSV MBS qua `/shadow upload` → auto-detect +
  parse đúng như SSI/VPS/TCBS.

### 📋 FEAT-6 More strategy skills
- **Những skill defer từ W3:**
  - `strategy/elliott-wave` — skeleton có trong PLAN_V2 §2.2
  - `strategy/harmonic` — Gartley/Butterfly/Bat/Crab
  - `strategy/chanlun` — phân tích 缠论 (có trong Vibe-Trading)
- **Done when:** 3 skill file mới với v2 frontmatter, human-readable
  rules, tests pass.

### 📋 FEAT-7 Real-advisor mode
- **Why:** Sau 3 tháng track record, user muốn bot chỉ gợi ý (không đặt
  lệnh simulator) + đồng bộ với trade thật.
- **Scope:**
  - New `MODE=advisor` env → simulator không fill, chỉ log proposal
  - `/confirm d42` Telegram → user xác nhận đã đặt lệnh thật → simulator
    treat như filled (với fill_price user nhập)
  - Weekly bias check compare bot's proposals vs user's actual actions
- **Done when:** User có thể chạy 3-6 tháng advisor mode + thấy alpha
  measurement accurate so với TKCK thật.

### 📋 FEAT-8 Skill A/B test framework
- **Why:** Hiện shadow phase chạy parallel nhưng không auto-compare. Nên
  có proper A/B harness: seed cùng context, run với skill A + skill B,
  measure delta decision rate + outcome.
- **Scope:** New `learning/ab_test.py` — register 2 skill variants, swarm
  rotate preset giữa 2, `/skill ab-test <parent> <variant>` trigger
  report sau 30 trades.
- **Done when:** Có thể ra verdict "variant beats parent 3% win-rate,
  p-value 0.04" — đi qua statistical gate của skill_lifecycle.

### 📋 FEAT-9 Web UI dashboard (minimal)
- **Scope:** FastAPI app ở port 8080 với 4 view:
  - `/decisions` — table với filter
  - `/skills` — stats + CI95 grid
  - `/bias` — weekly history
  - `/traces/<trace_id>` — replay DAG node-by-node
- **Dependencies:** FastAPI + Jinja2 (nếu không reuse report template).
- **Done when:** User mở `localhost:8080` thấy tất cả state đang có
  trong Telegram + thêm visualizations.

---

## P3 — Big features (1-2 tuần)

### 📋 BIG-1 Full OHLC shadow backtest (replace classification-based)
- **Hiện:** W5 shadow backtester classify real trade qua rule → delta-PnL
  attribute. Không thực sự replay strategy trên historical price.
- **Target:** Cho 1 ShadowRule, simulate strategy từ `start_date` đến
  `end_date` dùng OHLC daily trên mọi ticker phù hợp rule → compute real
  Sharpe/DD/win-rate nếu user follow rule strictly.
- **Done when:** `run_shadow_backtest(full=True)` trả thêm `strict_sharpe`,
  `strict_drawdown`, `strict_trade_count` — có thể khác Delta-PnL.

### 📋 BIG-2 Cross-market sleeve — CCXT crypto hedge
- **Why:** PLAN_V2 §7 defer. Vibe-Trading có. Nếu user muốn hedge VN
  equities với BTC/ETH (correlation âm trong risk-off).
- **Scope:** New `data/ccxt_client.py` + `skills/crypto/*` + simulator
  extension (24/7 trading, no T+2) + cross-asset position cap.
- **Done when:** Portfolio có thể hold 80% VN + 20% crypto với risk-parity
  rebalance weekly.

### 📋 BIG-3 Multi-timeframe intraday strategies
- **Why:** Hiện EOD only. Một số skills (breakout, momentum) work tốt
  hơn trên 30m/1h.
- **Scope:**
  - Fetch intraday OHLC (vnstock có qua `quote.history(interval='30')`)
  - Intraday skill variants
  - Separate cron per interval
- **Done when:** `/debate FPT 1h` chạy swarm với context intraday bars,
  proposals có timeframe annotation.

### 📋 BIG-4 Grafana/Prometheus metrics export
- **Why:** User muốn observability proper thay vì log grep.
- **Scope:** `prometheus_client` expose `/metrics` endpoint. Export:
  - `vnstock_bot_nav_vnd`
  - `vnstock_bot_decisions_total{action}`
  - `vnstock_bot_skill_win_rate_ci_low{skill}`
  - `vnstock_bot_bias_severity{bias}`
- **Done when:** Có dashboard JSON import vào Grafana → thấy 6-8 panel.

---

## P4 — Research / experimental

### 📋 RES-1 Factor zoo testing framework
- **Scope:** Auto-test 20 factor candidates (momentum, reversal, vol,
  volume ratio, PE, PB, ROE, foreign flow, net profit growth, etc.) mỗi
  tháng → pick top-5 IC → auto-propose `multi-factor` skill variant.
- **Done when:** `/factor-zoo` Telegram trả bảng 20 factor với IC + IR +
  quantile monotonicity.

### 📋 RES-2 LLM-driven skill proposer (beyond deterministic)
- **Hiện:** `skill_proposer.py` chỉ cluster pattern → emit draft template.
  Thiếu creativity.
- **Target:** Weekly job đưa cho Claude "30 decisions gần nhất + outcomes
  + existing skills" → prompt tạo skill NEW từ scratch (ngoài những
  pattern đã cluster).
- **Done when:** Bot tự tạo ≥ 1 skill mới không copy template mỗi tháng,
  được human approve qua `/skill promote`.

### 📋 RES-3 RL on skill weights
- **Scope:** Experiment: thay vì binary active/shadow, mỗi skill có weight
  ∈ [0, 1] trong `multi-factor` composite. RL tune weights via Thompson
  sampling với reward = weekly NAV delta.
- **Done when:** Có experimental branch chứng minh RL-tuned weights
  beat equal-weight ≥ 2% annual Sharpe.

### 📋 RES-4 Reinforcement-from-decision-outcomes
- **Why:** Hiện skill lifecycle là binary (promote/archive). Thiếu
  continuous feedback trên decision-level.
- **Target:** Mỗi decision outcome tạo reward signal → update
  "confidence score" của từng skill appearing trong `skills_used`.
  Research agent dùng confidence weighting khi load skill.
- **Done when:** Skill có "credit assignment": winning decisions bump
  weight, losing decisions decay. Visible trong `/skills` output.

---

## 📦 Đang block bởi resource bên ngoài

### ❌ vnstock data quality issues
- Không chủ động được — phụ thuộc upstream VCI/TCBS API ổn định.
- Mitigation: parquet cache + fallback giữa providers.

### ❌ Broker CSV format changes
- SSI/VPS đôi khi đổi layout export. Cần monitor + update parsers.

### ❌ Claude SDK rate limits
- Subscription tier giới hạn. Nếu chạy `/debate` + `/review` nhiều, có
  thể hit rate limit. Mitigation: token budget cảnh báo, fallback single
  mode.

---

## 🧭 Thứ tự đề xuất

Nếu bạn là dev solo part-time, làm theo thứ tự:

1. **Week 1:** P0 BUG-1, BUG-2, BUG-3, QUAL-1 (~ 2 ngày tổng)
2. **Week 2:** P1 WIRE-1 (bias_flags), WIRE-2 (L3 summaries), FEAT-1 (Excel)
3. **Week 3:** P1 INFRA-1 (Docker), DOC-1 (deploy guide)
4. **Week 4:** P1 FEAT-2 (pre-market briefing), FEAT-3 (backtest plot)
5. **Month 2:** P2 FEAT-7 (real-advisor mode) — critical nếu user muốn
   dùng thật
6. **Month 3+:** P3 BIG items, P4 experimental

Nếu bạn chỉ muốn **bot chạy production ổn định** → dừng ở cuối Week 2.
Từ đó trở đi là về chất lượng decisions qua forward-run 3-6 tháng,
không phải thêm code.

---

## 📝 Cách add backlog item

Khi phát hiện bug hoặc muốn feature mới:

1. Chọn tier phù hợp (P0-P4).
2. Template:
   ```
   ### 📋 <PREFIX>-<N> Title ngắn
   - **Why:** ...
   - **Scope:** ...
   - **Dependencies:** ...
   - **Done when:** ...
   ```
3. Prefix conventions:
   - `BUG-` sửa bug
   - `QUAL-` quality/CI/testing
   - `WIRE-` wire-up code đã có
   - `FEAT-` feature mới
   - `INFRA-` deployment/ops
   - `DOC-` documentation
   - `BIG-` ≥ 1 tuần effort
   - `RES-` research / experimental

4. Commit message: `backlog: add <ID> <short>` — tracked in git history.
