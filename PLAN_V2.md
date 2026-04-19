# vnstock-bot v2 — Thiết kế lại (Design only)

> **Mục tiêu:** Giữ DNA v1 (Telegram bot cá nhân, VN market, simulator chặt,
> T+2, int VND, no-lookahead, skills có đo lường) **+ chắt lọc tinh túy cụ
> thể** từ Vibe-Trading (skill templates, swarm DAG, shadow account logic,
> statistical validation).
>
> **Triết lý mới:** Bot không chỉ *ra quyết định* mà **tranh luận với chính
> mình trước khi chốt**, **biết mình đang bias gì**, và chỉ tin skill có
> **bằng chứng thống kê** (bootstrap CI, walk-forward), không tin point
> estimate.

---

## 0. TL;DR — v1 vs v2

| Khía cạnh | v1 | v2 |
|---|---|---|
| Quyết định | 1 agent tự làm hết | **Swarm DAG** (bull↔bear parallel → risk → PM) |
| Skills | 7 skill human-written | **25-30 skill** (port từ Vibe-Trading + VN-specific) có threshold cụ thể |
| Skill lifecycle | Weekly edit | **draft → shadow → active → archived** + bootstrap CI gate |
| Learning | Win-rate 5/10/20d | + **Monte Carlo permutation, Bootstrap 95% CI, Walk-forward** |
| Memory | strategy.md + DB | **5-layer FTS5 memory** (session/prefs/project/ref/history) |
| Self-awareness | — | **4 bias detector** với công thức + threshold Medium/High |
| User data input | — | **Shadow Account**: upload SSI/VPS CSV → extract 3-5 rule → backtest → Delta-PnL attribution |
| Backtest metrics | PnL, Sharpe | **15 metrics** + 3 validation method + 4 optimizer |
| Export | Markdown | + **Pine Script v6** + **HTML/PDF 8-section report** |
| Protocol | Telegram | + **MCP server** (Claude Desktop/Cursor) |

---

## 1. Kiến trúc tổng thể v2

```
┌──────────────────────────────────────────────────────────────────────────┐
│  vnstock_bot v2                                                          │
│                                                                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────────────┐   │
│  │ Telegram   │  │ APScheduler│  │ MCP stdio  │  │ CLI              │   │
│  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘  └────────┬─────────┘   │
│         └───────┬───────┴───────┬───────┴─────────────────┘              │
│                 │               │                                         │
│                 └───────┬───────┘                                         │
│                         ▼                                                 │
│          ┌────────────────────────────┐                                   │
│          │   Agent Orchestrator       │                                   │
│          │  (async DAG + swarm runner)│                                   │
│          └──┬─────────────────────┬───┘                                   │
│             ▼                     ▼                                       │
│     single-agent path       swarm presets (6)                             │
│     (chat, quick)           (daily, debate, review, macro, shadow)        │
│                                                                           │
│  ┌──────┬──────┬──────────┬──────┬────────┬────────┬────────┬────────┐   │
│  │Tools │Skills│Validator │Memory│Simulator│Learning│Shadow  │Bias    │   │
│  │  27  │25-30 │(Pydantic+│FTS5+ │(ATO/T+2 │(stats) │Account │Detector│   │
│  │      │      │ business)│5-layer│biên độ) │        │(4 tool)│(4 loại)│   │
│  └──────┴──────┴──────────┴──────┴────────┴────────┴────────┴────────┘   │
│                                                                           │
│  State: SQLite (bot.db) + DuckDB view + Git (skills/strategy) +           │
│         ~/.vnstock-bot/memory/*.md                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Skills System v2 — Chi tiết rule & threshold

### 2.1 Skill file format (port từ Vibe-Trading)

```yaml
---
name: factor-research
version: 1
status: active                    # draft | shadow | active | archived
category: analysis                # analysis | strategy | risk | flow | tool
description: Kiểm chứng factor qua IC/IR + quantile backtest
when_to_use: Khi có ý tưởng factor mới (momentum, PE, ROE…) muốn verify
inputs: [factor_series, forward_return, n_groups=5]
outputs: [ic_mean, ic_std, ir, ic_positive_ratio, quantile_equity]

# Statistical evidence (cập nhật bởi learning job)
uses: 47
trades_with_signal: 23
win_rate_20d: 0.61
win_rate_ci_95: [0.42, 0.78]       # bootstrap
walk_forward_stable: true
shadow_vs_parent: null
parent_skill: null
---

## Rules
1. IC mean > 0.05 → factor có tín hiệu thực
2. IR = IC_mean/IC_std > 0.5 → ổn định
3. Tỷ lệ IC > 0 > 55% → hướng ổn định
4. Top quantile return > Bottom quantile return (monotonic) → factor work

## Evidence required khi apply
- IC series 20 phiên gần nhất
- Quantile equity 5 group
- Sector breakdown

## Deprecated rules
(none)
```

### 2.2 Danh mục skill v2 (25-30 skill thay vì 7)

Port từ Vibe-Trading + VN-specific. Mỗi skill có **threshold số cụ thể** làm chuẩn apply:

#### **Analysis (8 skill)** — port nặng từ Vibe-Trading

| Skill | Rule chính / Threshold |
|---|---|
| `top-down-macro` | VN-Index vs SMA50/200; lãi suất OMO/tín phiếu; tỷ giá USD/VND; hướng FDI |
| `sector-rotation` | Xếp hạng 20 sector theo relative strength 20d; top 3 ưu tiên |
| `factor-research` | IC>0.05, IR>0.5, IC+ratio>55%, quantile monotonic |
| `valuation-model` | PE ≤ ngành_median × 1.1; PB ≤ 2.5 (ngân hàng ≤ 2.0); EV/EBITDA ≤ 10 |
| `multi-factor` | 3 cách gộp: equal-weight / IC-weighted / orthogonalized |
| `correlation-analysis` | Pairwise rolling 60d corr; cảnh báo nếu >0.7 trong holdings |
| `behavioral-finance` | Screen fear/greed của market qua put/call, vol breadth |
| `catalyst-check` | Earnings ±7 ngày, chia cổ tức, M&A, room ngoại |

#### **Strategy / Technical (9 skill)** — tinh túy TA từ Vibe-Trading

| Skill | Rule chính |
|---|---|
| `technical-basic` | SMA20/50/200, volume MA20, trend confirm ≥10 phiên |
| `candlestick` | **15 pattern** vectorized pandas: Hammer, Doji, Engulfing, Harami, Morning/Evening Star, 3 Soldiers/Crows (body_pct, shadow_ratio tunable) |
| `ichimoku` | Tenkan/Kijun cross + price vs Kumo cloud; chikou confirm |
| `smc` | **BOS/ChoCH/FVG/Order-Block**; swing_length=10, close_break=True |
| `elliott-wave` | 3 iron rules: W2 không vượt W1 start; W3 không shortest; W4 không overlap W1. Fib: W2=0.5-0.618, W3=1.618×W1 |
| `harmonic` | Gartley/Butterfly/Bat/Crab với Fib ratios chuẩn |
| `momentum` | RSI>55 + MACD hist dương + volume 1.5×MA20 → confirm |
| `mean-reversion` | Z-score giá vs SMA20 ≤ -2 + RSI < 30 → buy setup |
| `breakout` | Giá đóng > max(high, 20) + volume ≥ 2×MA20 |

#### **Risk & Portfolio (5 skill)**

| Skill | Rule |
|---|---|
| `position-sizing` | Kelly-lite: f* = min(edge/variance, 0.1); ≤20% NAV/mã |
| `stop-loss-rules` | Hard -8% hoặc invalidation hit; trailing 5% trên +15% |
| `correlation-check` | Không quá 2 mã corr > 0.7; ≤2 mã/ngành |
| `drawdown-budget` | Portfolio DD ≤ -15% → de-risk 50%; ≤-20% → all-cash |
| `regime-filter` | VN-Index dưới SMA200 = risk-off, max gross 60% NAV |

#### **Flow & Macro (4 skill)** — VN-specific

| Skill | Rule |
|---|---|
| `foreign-flow` | Net mua ròng ≥ 5 phiên liên tiếp = tín hiệu confirm |
| `proprietary-flow` | Tự doanh CTCK net-buy watchlist — có sẵn data vnstock |
| `derivative-basis` | VN30F1M basis vs VN30 spot; contango/backwardation |
| `liquidity-check` | ADV20 < 500k cp → không chơi (slippage lớn) |

#### **Tool skills (4)** — meta-skill

| Skill | Mục đích |
|---|---|
| `backtest-diagnose` | Chạy backtest + diagnose overfit (Sharpe>2 + low trade count = nghi) |
| `report-generate` | Sinh markdown/HTML report |
| `pine-script` | Export sang Pine v6 (template 5 pattern) |
| `doc-reader` | Đọc PDF BCTC, CSV, Excel user upload |

### 2.3 Skill lifecycle — CRUD có guardrail thống kê

```
[Draft]  ──(≥30 uses, CI95_low > 0.5)──> [Active]
   ↑         │
   │         └─(shadow parallel 30 trade, so với active)─┐
   │                                                      │
[Shadow]  ←─(proposed by skill_proposer)                  │
   │                                                      │
   └──(≥30 uses, CI95_upper < 0.5)──────> [Archived]      │
                                                          │
   Parent-Fork: skill v3 = fork(v2) + rule mới ───────────┘
```

**Quyết định gate:**
- **Draft → Shadow**: human approve (hoặc `/approve_draft` Telegram)
- **Shadow → Active**: ≥30 trade AND `ci95_lower > 0.5` AND beat parent ≥2% absolute win-rate AND walk-forward 3 window stable
- **Active → Archived**: ≥30 trade AND `ci95_upper < 0.5`
- **Edit skill**: ≤2 skill/tuần; bump version; git commit; walk-forward 3 window trên backtest history trước khi commit

### 2.4 `skill_proposer` — auto đề xuất skill mới

Subagent chạy trong weekly review:
- Input: 30-day decisions + outcomes + patterns từ memory L4.
- Output: 0-2 skill DRAFT (vd: "5/7 winner đều có vol > 2×MA20 trong 3 phiên liên tiếp → đề xuất skill `volume-surge-confirm`").
- Draft auto vào shadow phase (không fill thật, chỉ log).

---

## 3. Swarm DAG — 6 preset (port format YAML từ Vibe-Trading)

### 3.1 Preset file format (`config/swarm/*.yaml`)

```yaml
name: new_entry_debate
title: "Tranh luận trước khi BUY mới"
description: Bull vs Bear debate + Risk review + PM final call

agents:
  - id: bull_advocate
    role: "Bull-case researcher for {ticker}"
    system_prompt: |
      Bạn là người ủng hộ BUY {ticker}. Tìm 7 điểm upside:
      1. Upside drivers (macro/sector/company)
      2. Technical detail (MA, volume, breakout)
      3. Upside quantified (target price, %)
      4. Flow evidence (khối ngoại, tự doanh)
      5. Catalyst ≤30d
      6. Targets (bear/base/bull)
      7. Main counter-argument bạn thấy
    tools: [load_skill, get_price, get_fundamentals, search_memory]
    skills: [technical-basic, momentum, breakout, catalyst-check, foreign-flow]
    max_iterations: 10
    timeout_seconds: 60

  - id: bear_advocate
    role: "Bear-case researcher for {ticker}"
    system_prompt: |
      Bạn phản đối BUY {ticker}. Tìm 7 điểm downside: topping pattern,
      valuation bubble, fundamental deterioration, liquidity risk, tail risk…
    tools: [load_skill, get_price, get_fundamentals, search_memory]
    skills: [technical-basic, valuation-model, mean-reversion, correlation-check]

  - id: risk_officer
    role: "Chief risk officer"
    system_prompt: |
      Review bull + bear. KHÔNG chọn phe. Output:
      1. Validity check (claim nào của bull/bear có evidence, claim nào là hearsay)
      2. Risk scorecard (1-5) cho mỗi kịch bản
      3. Blind spots
      4. Position size recommendation
      5. Stops & invalidation khách quan
      6. Điều kiện để revisit
    tools: [load_skill, search_memory]
    skills: [position-sizing, stop-loss-rules, correlation-check, drawdown-budget]

  - id: portfolio_manager
    role: "PM final decision"
    system_prompt: |
      Synthesize bull+bear+risk. Output Pydantic Decision với:
      direction (BUY/WAIT/NO), size_pct, targets(bear/base/bull),
      confidence 0-100, bias_flags (nếu fit chase-momentum/anchoring),
      execution_plan (ATO phiên sau), invalidation.
    tools: [propose_trade, load_skill]

tasks:
  - id: t_bull
    agent_id: bull_advocate
    prompt_template: "Analyze bull case for {ticker} in VN market"

  - id: t_bear
    agent_id: bear_advocate
    prompt_template: "Analyze bear case for {ticker}"

  - id: t_risk
    agent_id: risk_officer
    depends_on: [t_bull, t_bear]
    input_from: {bull_report: t_bull, bear_report: t_bear}
    prompt_template: "Review debate for {ticker}"

  - id: t_decision
    agent_id: portfolio_manager
    depends_on: [t_risk]
    input_from: {full_debate: t_risk}
    prompt_template: "Final call for {ticker}"

variables:
  - {name: ticker, required: true}
  - {name: market, default: VN}
```

### 3.2 Sáu preset cho VN

| Preset | Trigger | Nodes | Giá trị mang lại |
|---|---|---|---|
| `quick_chat` | User text Telegram | 1 agent + context portfolio | Fallback, chat thường |
| `daily_research` | Cron 15:30 | researcher → sector_rotator → tech_panel(3 parallel) → drafter → risk_reviewer → PM | Quyết định daily có audit trail |
| `new_entry_debate` | Trước mỗi BUY | bull ↔ bear parallel → risk → PM (≤3 round) | Chống confirmation bias |
| `position_review` | Weekly + giá gần stop/target | fundamental_check + technical_check + invalidation_check (parallel) → decider | Hold/Trim/Sell có bằng chứng |
| `macro_sector_desk` | Sunday | macro + sector + foreign_flow (parallel) → regime_labeler | Gán regime risk-on/off cho tuần |
| `shadow_review` | User `/shadow upload` | parser → rule_extractor → shadow_backtester → report_renderer | Báo cáo HTML 8-section |

### 3.3 DAG runner requirements

- Async (dùng `asyncio.gather` cho parallel nodes).
- Per-node timeout (60s default), per-DAG timeout (3 phút).
- Streaming status về Telegram mỗi khi 1 node done: `✅ researcher (8s) → ⏳ technical_panel…`
- Fallback: nếu node fail, retry 1 lần, nếu vẫn fail → downgrade về single-agent + log alert.
- Replay: lưu DAG execution trace (trace_id) → `/why <decision_id>` có thể in lại full trace.

---

## 4. Memory System v2 — 5 layer FTS5

Port structure từ Vibe-Trading (`~/.vibe-trading/memory/*.md`).

### 4.1 5 layer

| Layer | Lưu ở đâu | TTL | Cap | Use case |
|---|---|---|---|---|
| **L1 Session Snapshot** | YAML frontmatter prepend vào system prompt | session | <200 dòng | Fast retrieval, cache hit |
| **L2 User Prefs** | `~/.vnstock-bot/memory/user_prefs.md` | persistent | 8KB | "Tôi risk-averse, không chơi UPCOM, prefer VN30" |
| **L3 Project Context** | `~/.vnstock-bot/memory/project_{name}.md` | persistent | 8KB/project | Backtest config, strategy state, watchlist |
| **L4 Reference** | `~/.vnstock-bot/memory/reference_*.md` | persistent | 8KB/ref | Lễ VN, KQKD dates, thresholds |
| **L5 Session History** | In-memory deque | session | context budget | Turn disambiguation |

### 4.2 FTS5 tokenization (VN-aware)

Vibe-Trading dùng ASCII regex `[a-zA-Z0-9_]{3,}` + CJK char-level. VN cần:
- **ASCII-accented Vietnamese**: normalize bằng `unicodedata.normalize('NFD')` → tokenize lowercase stem.
- **Token length ≥3** để tránh stop words.
- **Metadata weight 2.0x** trên body (title/description quan trọng hơn).

```python
def tokenize_vi(text: str) -> list[str]:
    normalized = unicodedata.normalize('NFD', text.lower())
    ascii_text = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    return re.findall(r'[a-z0-9_]{3,}', ascii_text)
```

### 4.3 Tools cho agent

- `search_memory(query: str, k: int = 5)` → top-k events/docs relevant.
- `get_timeline(ticker: str, days: int = 90)` → all events về 1 mã.
- `recall_similar_decision(current_ctx: dict)` → tìm decision cũ trong tình huống tương tự (dùng ticker + action + regime label).
- `write_memory(layer: str, key: str, content: str)` → agent tự ghi memory (L2, L3, L4).

### 4.4 5-layer compression khi prompt vượt budget

Khi DAG input > 40k token:
1. Giữ 5 message gần nhất (L1 raw).
2. Message 6-20: chunk summary (L2).
3. Message 21+: daily summary (L3).
4. Prepend patterns relevant (L4).
5. Prepend strategy.md bullets (L5).

---

## 5. Shadow Account — 4 tool + 8 section report

Đây là **killer feature** port trực tiếp từ Vibe-Trading.

### 5.1 4 tool

| Tool | Input | Output |
|---|---|---|
| `analyze_trade_journal` | `file_path`, `analysis_type="full"` | Trading profile (hold days, win rate, PnL ratio, DD) + 4 bias score |
| `extract_shadow_strategy` | `journal_path`, `min_support=3`, `max_rules=5` | `shadow_id` + 3-5 rule (human text ≤30 chars) |
| `run_shadow_backtest` | `shadow_id`, `journal_path` | Metrics + equity curve + Delta-PnL attribution |
| `render_shadow_report` | `shadow_id` | HTML + PDF path (8 section) |

### 5.2 Extract rule logic

```python
# Pseudocode
trades = parse_csv_fifo_pairing(file)                    # roundtrips
winners = [t for t in trades if t.pnl > 0]
clusters = groupby(winners, key=lambda t: (
    t.sector,                                             # VN-specific
    bucket_hour(t.entry_time),                            # 9:15/9:30/11:00/13:00/14:00
    bucket_holding(t.hold_days)                           # [1-2] [3-5] [6-10] [>10]
))
rules = []
for key, cluster in clusters.items():
    if len(cluster) >= min_support:
        rules.append(Rule(
            human_text=render(key, max_chars=30),          # "Mua ngân hàng phiên sáng, giữ 3-5 ngày"
            support_count=len(cluster),
            coverage_rate=len(cluster)/len(winners),
            holding_range=bucket_holding(cluster),
            sector=key.sector,
        ))
return rules[:max_rules]
```

### 5.3 Delta-PnL attribution (section 5, "cú đánh chí tử")

| Component | Công thức |
|---|---|
| `noise_trades_pnl` | Σ PnL của trade không match rule nào (emotion trades) |
| `early_exit_pnl` | Σ (would-be PnL khi giữ đến rule_max) − actual PnL, cho winner hold < rule_min |
| `late_exit_pnl` | Σ actual PnL − (would-be PnL khi cắt ở rule_max), cho loser hold > rule_max |
| `overtrading_pnl` | Σ PnL của trade vượt rule frequency (vd rule nói max 3 trade/tuần mà user làm 7) |
| `missed_signals_pnl` | Residual = shadow_pnl − user_pnl − (4 component trên) |

### 5.4 4 bias detector — CÔNG THỨC cụ thể

Giống Vibe-Trading, dùng cho cả user data (Shadow Account) và bot's own decisions (weekly self-check):

| Bias | Công thức | Medium | High | Ghi chú |
|---|---|---|---|---|
| **Disposition effect** | `avg_loser_hold / avg_winner_hold` | ≥ 1.2 | ≥ 1.5 | Giữ loser lâu hơn winner |
| **Overtrading** | `(quiet_day_avg_pnl − busy_day_avg_pnl) / \|quiet\|` | ≥ 0.3 | ≥ 1.0 | Càng trade nhiều càng lỗ |
| **Chase momentum** | `% buys after 3-day +3% move` | ≥ 40% | ≥ 60% | Mua đỉnh |
| **Anchoring** | `% symbols (≥5 trades) with entry-price CV < 5%` | ≥ 33% | ≥ 66% | Cứ bám 1 vùng giá |

Thêm 3 bias **bot-specific** (chạy trên bot decisions):

| Bias | Công thức | Ý nghĩa |
|---|---|---|
| **Hot-hand sizing** | `corr(prev_win, next_qty%)` > 0.4 | Tăng size sau win streak |
| **Skill dogma** | `% decisions dùng top-1 skill` > 70% | Chỉ dùng 1 skill, overfit |
| **Recency** | `% decisions citing "last week"` > 40% | Bám sự kiện gần |

### 5.5 8-section HTML/PDF report

```
1. Executive summary (rule recap, PnL gap)
2. Trading profile (hold days, frequency, top symbols, sector breakdown)
3. Shadow equity curve vs real (dual-line chart)
4. Rules detail (mỗi rule: human_text, support_count, coverage, win-rate)
5. ★ Delta-PnL attribution (noise/early/late/over/missed) — insight chính
6. Counterfactual Top-5 ("Nếu giữ FPT thêm 3 phiên → +1.1M"; "Nếu không mua VIC → +800k")
7. Per-sector comparison (NH tốt hơn BĐS?)
8. Actionable: "Nếu theo shadow rule, PnL năm +X%"
```

Render bằng Jinja2 template + WeasyPrint → PDF.

### 5.6 Parser support (VN brokers)

| Broker | Format | Priority |
|---|---|---|
| SSI iBoard | CSV export "Lịch sử lệnh" | P0 |
| VPS SmartOne | CSV "Lịch sử giao dịch" | P0 |
| TCBS | XLSX export | P1 |
| MBS | CSV | P1 |
| VND | CSV | P2 |
| Generic | Auto-detect 8 column map | Fallback |

---

## 6. Backtest v2 — 15 metrics + 3 validation + 4 optimizer

### 6.1 Config schema (JSON, port từ Vibe-Trading)

```json
{
  "source": "vnstock",
  "codes": ["FPT", "VNM", "HPG"],
  "start_date": "2025-10-01",
  "end_date": "2026-04-18",
  "interval": "1D",
  "initial_cash": 100000000,
  "commission": 0.0015,
  "tax_sell": 0.001,
  "lot_size": 100,
  "price_limit": {"HSX": 0.07, "HNX": 0.10, "UPCOM": 0.15},
  "settlement": "T+2",
  "extra_fields": ["pe", "pb", "roe", "foreign_buy_qty"],
  "optimizer": "risk_parity",
  "validation": {
    "monte_carlo": {"n_simulations": 1000, "alpha": 0.05},
    "bootstrap": {"n_bootstrap": 1000, "confidence": 0.95},
    "walk_forward": {"n_windows": 5, "train_ratio": 0.7}
  }
}
```

### 6.2 15 performance metrics

| Metric | Formula | VN threshold "đạt" |
|---|---|---|
| `final_value` | Ending NAV | ≥ initial × (1 + rf × years) |
| `total_return` | (final − initial) / initial | > VN-Index cùng kỳ |
| `annual_return` | `(1+total)^(252/bars) − 1` | > 12% |
| `max_drawdown` | min(equity/peak − 1) | > −25% |
| `sharpe` | `mean(ret)/std(ret) × √252` | > 1.0 (> 2.5 nghi overfitting) |
| `calmar` | `annual_return / \|max_dd\|` | > 1.0 |
| `sortino` | `mean(ret)/downside_std × √252` | > 1.5 |
| `win_rate` | wins / total_trades | > 50% |
| `profit_loss_ratio` | avg_win / \|avg_loss\| | > 1.5 |
| `profit_factor` | gross_profit / \|gross_loss\| | > 1.2 |
| `max_consec_loss` | longest losing streak | < 5 |
| `avg_holding_days` | mean trade duration | 5-20 (swing) |
| `trade_count` | # completed roundtrips | > 30 (meaningful) |
| `benchmark_return` | VN-Index | — |
| `excess_return` | strategy − VN-Index | > 0 |
| `information_ratio` | excess_mean/tracking_err × √252 | > 0.5 |

### 6.3 3 validation methods

| Method | Logic | Pass criteria |
|---|---|---|
| **Monte Carlo permutation** | Shuffle trade order 1000 lần, tính Sharpe distribution | Real Sharpe > 95% permuted → p < 0.05 |
| **Bootstrap** | Resample returns có thay thế 1000 lần, tính Sharpe CI 95% | CI95 không chứa 0 |
| **Walk-forward** | Chia N=5 window, train 70% / test 30% mỗi window | ≥4/5 window có Sharpe > 0.5 |

Skill chỉ được **promote → active** khi backtest historical data pass **≥2/3 method**.

### 6.4 4 optimizer

| Optimizer | Logic | Khi dùng |
|---|---|---|
| `equal_volatility` | weight_i = 1/σ_i, normalize | Danh mục nhiều mã vol chênh nhau |
| `risk_parity` | weight_i ∝ 1/σ²_i (equal risk contribution) | Production default |
| `mean_variance` | Markowitz: max Sharpe với constraint | Khi có view return |
| `max_diversification` | max (Σ w_i σ_i) / σ_portfolio | Giảm concentration |

---

## 7. Decision schema v2 — Pydantic đầy đủ

```python
class DecisionV2(BaseModel):
    # === v1 fields (giữ nguyên) ===
    ticker: str
    action: Literal["BUY","ADD","TRIM","SELL","HOLD"]
    qty: int
    target_price: int | None         # VND int
    stop_loss: int | None
    thesis: str
    evidence: list[str]              # ≥3 bullets, số liệu cụ thể
    risks: list[str]                 # ≥1 bullet
    invalidation: str                # khách quan
    skills_used: list[str]
    playbook_used: str | None
    conviction: int                  # 1-5

    # === v2 additions ===
    # Swarm trace
    swarm_preset: str | None         # "new_entry_debate"
    trace_id: str                    # UUID, replay-able
    parent_decision_id: str | None   # ADD/TRIM → ref decision ban đầu
    debate_rounds: int = 0
    bull_case: str | None
    bear_case: str | None
    risk_officer_notes: str | None
    judge_reasoning: str | None

    # Statistical
    skill_ci_lower_min: float | None # min CI95 lower trong skills_used
    walk_forward_pass: bool | None

    # Memory
    similar_past_decisions: list[str] # decision_id list từ recall
    pattern_match: str | None         # từ L4 memory

    # Bias self-check
    bias_flags: list[Literal[
        "chase_momentum", "hot_hand", "skill_dogma",
        "recency", "anchoring", "disposition"
    ]] = []

    # Targets 3-scenario (Vibe-Trading pattern)
    target_bear: int | None
    target_base: int | None
    target_bull: int | None

    # Execution
    size_pct_nav: float              # % NAV, check vs position-sizing skill
    execution_note: str              # "fill ATO phiên T+1"
```

---

## 8. Tech stack delta

| Layer | v1 | v2 | Lý do |
|---|---|---|---|
| DB | SQLite | SQLite + **DuckDB read-only view** | Rolling window stats, bootstrap nhanh |
| Search | SQL LIKE | **SQLite FTS5 + VN tokenizer** | Cross-session memory |
| Stats | pandas | pandas + **scipy.stats** + **arch** | Bootstrap, MC, walk-forward |
| Charting | — | **matplotlib** (PNG Telegram) + **Jinja2+WeasyPrint** (HTML/PDF) | Shadow report |
| Scheduler | APScheduler | APScheduler + **async DAG runner** (200 LOC) | Swarm |
| Export | — | **Pine Script v6 generator** | TradingView test |
| Protocol | Telegram | + **MCP stdio server** | Expose cho Claude Desktop |
| LLM | Claude Agent SDK | Claude SDK + fallback **Ollama local** (llama3.1) | Dev/offline |
| Memory | strategy.md | `~/.vnstock-bot/memory/*.md` (5 layer) | Port từ Vibe-Trading |

**Giữ nguyên:** Python 3.12, uv, python-telegram-bot v21, vnstock, Pydantic v2, structlog, int VND, T+2, biên độ, no-lookahead, Asia/Ho_Chi_Minh.

---

## 9. Cấu trúc thư mục

```
vnstock-bot/
├── PLAN_V2.md
├── skills/
│   ├── analysis/           # 8 skill (factor-research, valuation, sector-rotation, …)
│   ├── strategy/           # 9 skill (candlestick 15 patterns, ichimoku, smc, elliott, …)
│   ├── risk/               # 5 skill (position-sizing, stop-loss, regime-filter, …)
│   ├── flow/               # 4 VN-specific (foreign-flow, derivative-basis, …)
│   ├── tool/               # 4 meta (backtest-diagnose, pine-script, …)
│   ├── _shadow/            # skill đang shadow test
│   └── _archive/           # skill archived
│
├── config/
│   └── swarm/              # 6 YAML preset
│       ├── quick_chat.yaml
│       ├── daily_research.yaml
│       ├── new_entry_debate.yaml
│       ├── position_review.yaml
│       ├── macro_sector_desk.yaml
│       └── shadow_review.yaml
│
├── src/vnstock_bot/
│   ├── main.py
│   ├── config.py
│   │
│   ├── orchestrator/                       ← NEW
│   │   ├── dag.py                          # async DAG runner
│   │   ├── preset_loader.py                # load swarm YAML → DAG
│   │   ├── nodes.py                        # subagent factory
│   │   └── streaming.py                    # Telegram progress update
│   │
│   ├── memory/                             ← NEW
│   │   ├── layers.py                       # 5-layer abstraction
│   │   ├── fts5_index.py                   # + VN tokenizer
│   │   ├── compression.py                  # 5-layer compressor
│   │   └── recall.py                       # similar-decision lookup
│   │
│   ├── shadow/                             ← NEW
│   │   ├── parsers/                        # SSI, VPS, TCBS, MBS, generic
│   │   ├── rule_extractor.py               # FIFO pairing + cluster
│   │   ├── backtester.py                   # shadow replay
│   │   ├── delta_pnl.py                    # 5-component attribution
│   │   └── report.py                       # Jinja2 + WeasyPrint
│   │
│   ├── bias/                               ← NEW
│   │   ├── detectors.py                    # 4 công thức + 3 bot-specific
│   │   ├── weekly_check.py                 # chạy trên bot decisions
│   │   └── thresholds.py                   # Medium/High config
│   │
│   ├── learning/
│   │   ├── scorer.py
│   │   ├── skill_scorer.py
│   │   ├── stats.py                        ← NEW: bootstrap, MC, walk-forward
│   │   ├── skill_proposer.py               ← NEW
│   │   ├── skill_lifecycle.py              ← NEW: draft/shadow/active/archive
│   │   └── weekly_review.py
│   │
│   ├── backtest/
│   │   ├── runner.py
│   │   ├── metrics.py                      ← mở rộng 15 metrics
│   │   ├── optimizers.py                   ← NEW: 4 optimizer
│   │   └── validation.py                   ← NEW: MC/bootstrap/walkforward
│   │
│   ├── export/                             ← NEW
│   │   └── pine_script.py                  # 5 template
│   │
│   ├── mcp/                                ← NEW
│   │   └── server.py                       # read-only tools expose
│   │
│   ├── telegram/                           (giữ + /shadow, /debate, /bias, /why)
│   ├── data/                               (giữ)
│   ├── research/                           (giữ — single-agent fallback)
│   ├── portfolio/                          (giữ)
│   └── db/
│       ├── schema.sql                      (mở rộng: events, events_fts, patterns, shadow_*)
│       └── duckdb_views.sql                ← NEW
│
├── data/
│   ├── bot.db
│   ├── bot.duckdb
│   ├── shadow/                             # user uploads
│   └── reports/                            # HTML/PDF
├── ~/.vnstock-bot/memory/                  # 5-layer memory files
└── tests/
```

---

## 10. Lệnh Telegram v2

| Lệnh | Chức năng |
|---|---|
| `/status`, `/portfolio`, `/today`, `/decisions`, `/report week`, `/skills`, `/backtest 6mo` | giữ từ v1 |
| `/debate FPT BUY` | Kích `new_entry_debate` swarm |
| `/shadow upload` | Hướng dẫn upload CSV broker |
| `/shadow report` | Render HTML shadow gần nhất |
| `/bias` | Bias report tuần (bot + user nếu có shadow) |
| `/skill status technical-trend` | Version, CI, walk-forward result, A/B vs parent |
| `/skill promote draft-name` | Human approve draft → shadow |
| `/recall FPT` | Timeline + decisions cũ |
| `/export pine FPT-breakout` | Sinh Pine Script v6 |
| `/regime` | Regime label từ macro_sector_desk |
| `/why <decision_id>` | Replay full DAG trace |

---

## 11. Daily research flow v2 — end-to-end

```
15:30 Asia/Ho_Chi_Minh
  ├─> is_trading_day? NO → skip heartbeat → exit
  ├─> fetch watchlist OHLC (parquet cache → vnstock fallback)
  ├─> market_snapshot + foreign_flow + derivative_basis
  ├─> simulator: fill pending ATO, T+2 aging, stop-loss check (-8% hard)
  │
  ├─> orchestrator.run("daily_research", {date, watchlist, portfolio})
  │    │
  │    ├─ N1 researcher (top-down-macro + catalyst-check)
  │    │    → MarketContext {regime, rates_direction, top_sectors}
  │    ├─ N2 sector_rotator (sector-rotation)
  │    │    → [sector_rank]
  │    ├─ N3 (parallel × ticker) technical_panel
  │    │    → 3 skill (technical-basic + momentum + candlestick) vote
  │    │    → resonance_score ∈ [-5, +5]
  │    ├─ N4 drafter (multi-factor + valuation-model)
  │    │    → [DecisionDraft]
  │    ├─ N5 (conditional: action∈{BUY,ADD}) new_entry_debate sub-DAG
  │    │    → bull ↔ bear × ≤3 round → PM
  │    ├─ N6 risk_reviewer (position-sizing + correlation-check + drawdown-budget)
  │    │    → veto vi phạm hard rule
  │    └─ N7 PM_final
  │         → bias detector apply (chase_momentum/hot_hand)
  │         → final [DecisionV2]
  │
  ├─> validator: Pydantic + business rules + skill_ci_lower_min > 0.45 AND
  │              skill walk_forward_pass = true
  ├─> insert decisions + orders pending + memory events L1
  ├─> daily_equity row (DuckDB view auto-refresh)
  └─> telegram.send_report
        - 📈 NAV/P&L/vs VN-Index
        - 🤖 N decisions (+ link /why trace_id)
        - ⚠️ M rejected + lý do
        - 🏴 K bias flag hôm nay
        - 🔁 J skill in shadow
```

---

## 12. Guardrails KHÔNG thay đổi (từ v1)

1. **No lookahead** — data ≤ close hôm nay, fill ATO hôm sau.
2. **T+2** — `qty_available` vs `qty_total`.
3. **Biên độ** — ±7/±10/±15 theo sàn, validator reject.
4. **int VND** — không float.
5. **Position caps** — ≤20% NAV/mã, ≤10 vị thế, ≤2 mã/ngành, ≤0.7 corr.
6. **Stop -8%** — override phải log + playbook ref.
7. **Whitelist chat** — 1 user.
8. **Skill edit via git** — ≤2/tuần, version bump, walk-forward pass.
9. **Simulator mode** — không đặt lệnh thật trong MVP v2.
10. **MCP expose read-only** — không expose `propose_trade`.

---

## 13. Roadmap 6 tuần

**W1 — Memory + FTS5 VN tokenizer**
DB migration (events, events_fts, patterns, summaries); 5-layer API; `search_memory`/`recall_similar_decision` tools; test recall trên 3 tháng fixture.

**W2 — DAG orchestrator + YAML preset loader**
`orchestrator/dag.py` async runner; `preset_loader.py`; 2 preset đầu (`quick_chat`, `daily_research`); Telegram streaming; test timeout/fallback.

**W3 — Skills mở rộng + 4 preset còn lại**
Port 20+ skill từ Vibe-Trading (candlestick 15 pattern, factor-research, ichimoku, SMC, valuation…); thêm 4 preset còn lại (debate, review, macro, shadow); bull-bear hội tụ test.

**W4 — Statistical validation + skill lifecycle**
`learning/stats.py` (bootstrap, MC permutation, walk-forward); skill status machine; `skill_proposer`; decision schema v2 migration; bias detectors 7 loại.

**W5 — Shadow Account (killer feature)**
4 parser VN broker; rule extractor FIFO + cluster; shadow backtester; Delta-PnL 5 component; Jinja2 8-section HTML + WeasyPrint PDF; `/shadow upload` handler.

**W6 — Export + MCP + polish**
Pine Script v6 generator (5 template); MCP stdio server (read-only); DuckDB views; `/regime`, `/why`, `/export pine` commands; full E2E test.

**Post-MVP (khi có 3 tháng alpha dương):**
- Cross-market sleeve (CCXT OKX cho crypto hedge).
- Multi-timeframe (30m/1H intraday signals).
- Real-advisor mode (gợi ý, user tự đặt).

---

## 14. Success criteria

1. **Alpha định lượng**: 3 tháng forward-live có Sharpe > VN-Index AND max DD < VN-Index.
2. **Skill health**: ≥60% active skill có CI95 lower > 0.5 AND walk-forward pass ≥3/5.
3. **Bias self-discipline**: weekly bot bias report không còn flag High sau 8 tuần.
4. **Shadow utility**: user upload broker export → bot chỉ ra ≥3 cải thiện định lượng (Delta-PnL attribution chi tiết).
5. **Reliability**: daily job success ≥98% trong 60 ngày, p95 latency <60s.
6. **Reproducibility**: replay `trace_id` ra kết quả identical.
7. **Statistical rigor**: mọi skill promote → active pass ≥2/3 validation method.

---

## 15. Tóm tắt — vì sao v2 là "coach có bằng chứng" chứ không còn chỉ là bot simulator

| Tinh túy Vibe-Trading | Vào v2 ở đâu | Tại sao mạnh cho retail VN |
|---|---|---|
| 71 skill có threshold cụ thể | §2.2 — 25-30 skill VN | Replace "Claude cảm thấy…" bằng rule-book đo lường được |
| Swarm DAG YAML preset | §3 — 6 preset VN | Bull↔Bear debate ép bot nghĩ 2 mặt, chống confirmation bias |
| 5-layer memory + FTS5 | §4 | Bot nhớ lý do cắt FPT 3 tháng trước, không lặp lỗi cũ |
| Self-evolving skill CRUD | §2.3-2.4 | Bot tự đề xuất skill, A/B test, chỉ promote khi có CI |
| Shadow Account + 4 bias | §5 | User bridge simulator ↔ real: "mày để lại 3.2M trên bàn vì bias hot-hand" |
| 15 metrics + 3 validation + 4 optimizer | §6 | Sharpe đơn lẻ → bộ 15 + MC/bootstrap/walk-forward thay cho "eyeball" |
| Pine Script export + MCP | §7-8 | Mở rộng ngoài Telegram: TradingView real-time + Claude Desktop workflow |

**v1:** simulator + single-agent.
**v2:** swarm có bằng chứng thống kê + tự nhận bias + dùng dữ liệu giao dịch thật của user để calibrate.
