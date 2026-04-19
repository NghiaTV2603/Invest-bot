# Skills — index cho Claude (v2)

Mỗi skill là 1 "góc nhìn phân tích" tái dùng được với **rule + threshold cụ
thể**. Playbook là quy trình cho tình huống cụ thể (thường = compose nhiều
skill).

## Meta-rules (Claude PHẢI đọc trước mọi quyết định)

1. **Không bịa số.** Mọi con số trong `evidence` phải đến từ `get_price`,
   `get_fundamentals`, hoặc `market_snapshot`. Nếu không có tool tương ứng,
   viết "data unavailable" — đừng đoán.
2. **Mỗi proposal ≥ 1 skill + 1 playbook.** Điền `skills_used` và `playbook_used`.
3. **`invalidation` bắt buộc khách quan.** Phải là điều kiện đo được tự động
   (giá, khối lượng, ngày, chỉ số). Không viết "tâm lý thị trường xấu đi".
4. **Conviction thấp → qty thấp.** Conviction 1–2: bỏ qua (HOLD). Conviction
   3: đề xuất ≤ 10% NAV. Conviction 4–5: tối đa 20% NAV.
5. **Khi confused, đề xuất HOLD.** Không bắt buộc phải có trade mỗi ngày.

## v2 Status system

Mỗi skill có field `status` trong frontmatter:
- `draft`: mới tạo (human hoặc bot đề xuất). **Không được dùng** trong live decision.
- `shadow`: áp dụng song song với active skill, chỉ log để so A/B.
- `active`: chính thức dùng.
- `archived`: giữ code, không load.

Agent chỉ **load skill có `status: active`**. Weekly review (`learning/stats.py`)
promote draft → shadow → active theo statistical gate (≥30 uses, CI95 low > 0.5,
walk-forward pass).

## Index theo category

### 📊 Analysis (8 skill)

| Skill | When to use |
|---|---|
| `analysis/top-down-macro` | Bối cảnh thị trường chung (VN-Index, khối ngoại, lãi suất) |
| `analysis/technical-trend` | Trend + support/resistance + breakout signal cho 1 mã |
| `analysis/fundamental-screen` | Chất lượng doanh nghiệp (ROE, D/E, EPS growth) — hard gate |
| `analysis/catalyst-check` | Verify ticker có catalyst (KQKD, M&A, cổ tức, policy) ≥ 3 |
| `analysis/sector-rotation` | Top/bottom sector theo RS 20d — ưu tiên mã top, tránh bottom |
| `analysis/factor-research` | Test 1 factor có predictive power — IC > 0.05, IR > 0.5 |
| `analysis/multi-factor` | Combine 3-5 factor đã test thành composite score |
| `analysis/valuation-model` | PE/PB/EV-EBITDA vs median ngành VN → fair value |

### 📈 Strategy / Technical (6 skill — port Vibe-Trading)

| Skill | When to use |
|---|---|
| `strategy/candlestick` | 15 pattern nến vectorized — compound score [-3, +3] |
| `strategy/ichimoku` | Trend + Kumo cloud + Tenkan/Kijun cross + Chikou confirm |
| `strategy/smc` | Smart Money Concepts — BOS / ChoCH / FVG / Order Block |
| `strategy/momentum` | RSI + MACD + volume cộng hưởng — score [-3, +3] |
| `strategy/breakout` | Phá đỉnh 20 phiên + volume ≥ 2×MA20 |
| `strategy/mean-reversion` | Z-score ≤ -2 + RSI < 30 trong uptrend dài hạn |

### 🛡️ Risk (5 skill)

| Skill | When to use |
|---|---|
| `risk/position-sizing` | Quyết định qty (Kelly-lite, ≤ 20% NAV) |
| `risk/stop-loss-rules` | Stop cho vị thế mới / trailing cập nhật |
| `risk/correlation-check` | ≤ 2 mã/sector, corr pairwise < 0.7 |
| `risk/drawdown-budget` | Portfolio DD → max gross exposure (-15% → 60%, -20% → 30%) |
| `risk/regime-filter` | VN-Index vs SMA200 → allowed actions (hard gate) |

### 💸 Flow (2 skill — VN-specific)

| Skill | When to use |
|---|---|
| `flow/foreign-flow` | Khối ngoại mua/bán ròng ≥ 5 phiên → conviction modifier ±1 |
| `flow/liquidity-check` | ADV20 < 100k cp → block; tier 1/2/3/4 cho size cap |

### 🧰 Tool (2 skill — meta)

| Skill | When to use |
|---|---|
| `tool/backtest-diagnose` | 15 metrics + red flag check (Sharpe > 2.5 → overfit) |
| `tool/pine-script` | Export strategy sang Pine v6 cho TradingView |

## Index — playbooks

| Playbook | Trigger |
|---|---|
| `playbooks/new-entry` | Muốn BUY ticker chưa có trong holdings |
| `playbooks/cut-loser` | Holdings vi phạm stop-loss hoặc thesis đã sai |

## Cách load skill

Dùng tool `load_skill(name)`, ví dụ `load_skill("strategy/smc")`. **Chỉ load
skill thực sự cần** — progressive disclosure, không nuốt hết đầu vòng.

Gợi ý flow:
1. **Daily research open**: `load_skill("analysis/top-down-macro")` + `load_skill("analysis/sector-rotation")`.
2. **Per-ticker deep dive**: `analysis/technical-trend` → 1-2 strategy skill
   phù hợp context (breakout nếu phá đỉnh, mean-reversion nếu oversold…).
3. **Trước propose_trade**: `risk/position-sizing` + `risk/stop-loss-rules` +
   `risk/correlation-check`.
4. **Nếu BUY mới**: `analysis/catalyst-check` bắt buộc (playbook new-entry
   checklist 7 bước).

## Combine patterns (thực nghiệm)

| Setup | Skills to combine |
|---|---|
| Breakout entry | top-down-macro + sector-rotation + breakout + foreign-flow + liquidity-check + position-sizing |
| Oversold bounce | top-down-macro + valuation-model + mean-reversion + stop-loss-rules |
| Momentum ride | technical-trend + momentum + candlestick (confirm) + drawdown-budget |
| Position review | technical-trend + ichimoku (trailing) + stop-loss-rules |
| Exit signal | candlestick (bearish reversal) + smc (bearish ChoCH) + foreign-flow (persistent sell) |

## Versioning (v2)

- Mỗi skill có `version` trong frontmatter. Weekly review có thể bump version.
- **Gate chặt hơn v1**: skill chỉ được edit + active trở lại khi walk-forward
  3 window pass. Xem `learning/stats.py` (đang được làm ở W4).
- Frontmatter v2 có CI fields (`win_rate_ci_95`, `walk_forward_stable`…) —
  **populated tự động**, không hand-edit.

## Folder structure

```
skills/
├── README.md                 (file này)
├── analysis/                 8 skill
├── strategy/                 6 skill (port Vibe-Trading)
├── risk/                     5 skill
├── flow/                     2 skill (VN-specific)
├── tool/                     2 skill (meta)
├── playbooks/                2 playbook
├── _shadow/                  (W4 — skill đang shadow test)
└── _archive/                 (W4 — skill archived)
```
