# vnstock-bot

**Bot giao dịch chứng khoán Việt Nam có kỷ luật thống kê — tranh luận với
chính mình trước mỗi quyết định, tự kiểm tra bias, tự học từ outcome thật.**

Không phải "hỏi AI FPT có nên mua không". Đây là một hệ thống research có
quy trình: mỗi skill đi kèm **bootstrap CI 95%**, mỗi decision kèm
**DAG trace** để replay, mỗi tuần bot chấm điểm chính mình qua **7 bias
detector**. Mục tiêu: sau 3 tháng forward-run, có **bằng chứng định lượng**
skill nào tạo alpha, bias nào đang kéo tài khoản xuống.

> ⚠️ **Disclaimer:** Bot cá nhân, chạy local, **không phải lời khuyên đầu
> tư**. Mọi quyết định đặt lệnh thật là của bạn.

---

## 🎯 Tại sao khác với các bot khác

| Bot thông thường | vnstock-bot |
|---|---|
| "AI thấy FPT tốt" | Mỗi decision có `skills_used`, `evidence ≥ 3 bullet có số`, `invalidation khách quan` |
| Backtest một lần, tin luôn | **Bootstrap CI + walk-forward + Monte Carlo** — skill chỉ được *active* khi CI95 lower > 0.5 với ≥30 trades thật |
| Bỏ qua bias | **7 bias detector** tự chạy hàng tuần trên decisions của CHÍNH BOT (disposition, overtrading, chase momentum, hot-hand…) |
| Một agent làm hết | **Swarm DAG**: bull ↔ bear tranh luận song song → risk officer review → PM chốt, với `trace_id` replay được |
| Skill do dev cứng | **Self-evolving**: bot tự extract pattern từ winning decisions → đề xuất draft skill mới mỗi tuần |
| Không biết so với real money | **Shadow Account**: upload CSV lịch sử broker thật → bot extract rule bạn đang theo → chỉ ra bạn mất bao nhiêu vì phá rule |

---

## 🧠 Cách bot "suy nghĩ" — ví dụ cụ thể

Khi cron 15:30 fire hoặc bạn gõ `/today`, bot đi qua pipeline này:

```
📊 Market snapshot        VN-Index 1812, khối ngoại +120 tỷ, top KBC +1.7%
       ▼
🧾 Settle phiên trước     Fill pending orders ATO → T+2 tick → stop-loss check
       ▼
🔬 Research watchlist     Claude load skills theo context:
                           ├─ top-down-macro      → regime UPTREND
                           ├─ sector-rotation     → Steel RS 20d rank #2
                           ├─ technical-trend     → HPG close > SMA50 > SMA200
                           ├─ breakout            → close > max(high, 20) ✓
                           ├─ foreign-flow        → net +8.2B 5 phiên ✓
                           ├─ liquidity-check     → ADV 2.1M cp → Tier 1
                           ├─ catalyst-check      → KQKD Q1 trong 7 ngày ✓
                           └─ position-sizing     → 20% NAV cap
       ▼
🎯 Propose decision        d#42 BUY HPG qty=200 @ target 30,500 stop 26,800
                           evidence: 4 bullets có số (close, volume, flow, RS)
                           invalidation: close < 27,500 trong 2 phiên
                           conviction: 4 | skills: [7] | playbook: new-entry
       ▼
✅ Validator chain         Pydantic + biên độ + 20% cap + ≤ 2 mã/sector
                           → reject nếu vi phạm hard rule (không ai override)
       ▼
📝 Persist + place order   decisions.trace_id link DAG replay
                           orders.status='pending' → fill ATO phiên sau
       ▼
📲 Telegram report         Render decisions + fill history + alpha vs VN-Index
```

Khi gặp mã khó quyết định, bạn gõ `/debate HPG` → kích **swarm 4-node**:
```
bull_advocate (7 lý do MUA) ──┐
                               ├→ risk_officer → portfolio_manager (BUY/WAIT)
bear_advocate (7 lý do KHÔNG) ─┘
                                Parallel
```
Kết quả kèm `trace_id` → `/why a3f7bc...` xem chi tiết từng agent đã nói gì.

---

## 🔁 Vòng lặp tự học

Đây là phần thực sự khác biệt. Mỗi chủ nhật 10:00:

```
1. Chấm điểm decisions 5/10/20 phiên qua
   → thesis_valid? invalidation_hit? pnl_pct? → decision_outcomes

2. Compute stats per skill (bootstrap CI 95% + walk-forward)
   → breakout skill: 34 uses, ci_low=0.58, ci_high=0.79, wf_pass=4/5

3. Skill lifecycle FSM                    ┌─ ≥30 uses
   draft → shadow → active → archived     ├─ CI95 lower > 0.5
   (promote qua statistical gate,         ├─ walk-forward ≥ 3/5
    không phải win-rate point estimate)   └─ beat_parent ≥ 2%

4. Bias self-check trên decisions 90d
   🟢 disposition_effect  ratio=1.05  OK
   🔴 skill_dogma         75% decisions dùng technical-trend  ← cảnh báo
   🟡 overtrading         busy_day PnL xấu hơn quiet_day      ← theo dõi

5. L4 pattern extraction
   → phát hiện 5/7 winners đều có "breakout + foreign-flow + vol > 2x MA20"
   → skill_proposer gợi draft: "volume-surge-confirm"

6. Claude weekly_review
   → edit ≤ 2 skill/tuần qua git commit
   → append bullet vào strategy.md với decision_id tham chiếu
```

Sau 8-12 tuần, skill nào có edge thực sự sẽ **tự động** được promote lên
`active`; skill nào tệ sẽ **tự động** archived. Bạn không cần tinkering —
bot có FSM kỷ luật hơn nhiều con người.

---

## 👥 Shadow Account — killer feature

Bạn có export CSV từ SSI / VPS / TCBS không? Gửi vào Telegram:

```
User: (attach trades_2025.csv)
Bot:  ⏳ Parsing 247 trades (156KB)...

  ✅ Shadow shadow_abc123
  Trades: 247 (123 roundtrips), win-rate 41%
  Rules extracted: 3
   ├─ "Mua ngân hàng sáng sớm, giữ 3-5 ngày" (support 18, win-rate 72%)
   ├─ "Bán sau 2 phiên xanh liên tiếp"       (support 12, win-rate 65%)
   └─ "Tránh mã UPCOM ADV < 500k"            (support 9, win-rate 78%)

  Real PnL:    +12,400,000 VND
  Shadow PnL:  +28,900,000 VND (nếu theo rule chính bạn)
  Δ:           +16,500,000 VND mất vì phá rule

  📊 Delta-PnL attribution:
   🔴 Noise trades (không match rule):  -4,200,000 VND (emotion trades)
   🟡 Early exit winners:               -6,800,000 VND (cắt sớm)
   🟡 Late exit losers:                 -3,400,000 VND (giữ loser quá lâu)
   🟢 Overtrading cost:                   -890,000 VND
   🟢 Missed signals:                   -1,210,000 VND

  Report: data/reports/shadow/shadow_abc123.html (8 section + biểu đồ)
```

Nói cách khác: bot **không bảo bạn phải làm gì mới**, nó chỉ ra **bạn đã
có rule tốt sẵn, nhưng chính bạn là người phá nó**. Đây là cái mà
coach trading thật tính hàng nghìn USD để làm cho bạn.

---

## ⚡ Các tính năng chính

### Hằng ngày — tự động lúc 15:30 (thứ 2-6)
- Snapshot thị trường (VN-Index, khối ngoại, top movers, GTGD)
- Fill orders pending @ ATO phiên sau (T+2 settlement, phí 0.25%)
- Auto stop-loss: mã vượt -8% → emit SELL đi qua validator
- Research watchlist qua **23 skills** có threshold cụ thể (không phải AI vibes)
- Validate mọi proposal: Pydantic + biên độ (±7/10/15) + 20% NAV cap + ≤2 mã/sector
- Report Telegram với `trace_id` + `decision_id` để replay được

### Hằng tuần — chủ nhật 10:00
- Score decisions 5/10/20 phiên qua invalidation
- Bootstrap CI 95% + walk-forward cho mỗi skill
- 7 bias detector trên bot's own decisions + persist `bias_reports`
- Skill lifecycle FSM (draft → shadow → active → archived)
- L4 pattern extract → skill proposer đề xuất draft
- Claude weekly_review có thể edit skills/*.md với git commit

### Ad-hoc qua Telegram
| Lệnh | Dùng khi |
|---|---|
| `/debate FPT` | Phân vân 1 mã → swarm bull↔bear tranh luận (60-90s) |
| `/review FPT` | Holding gần stop/target → 3 parallel check + decider |
| `/shadow upload` | Có CSV broker thật → auto analyze + Delta-PnL HTML |
| `/bias` | Check bot đang drift bias gì tuần này |
| `/why <trace_id\|d42>` | Replay DAG node-by-node cho decision cụ thể |
| `/recall FPT` | Timeline + decision cũ về 1 mã (cross-session memory) |
| `/regime` | Regime tuần này: risk-on/off từ macro_sector_desk swarm |
| `/export pine ichimoku` | Sinh Pine Script v6 để test trên TradingView |
| `/today` / `/today_swarm` | Trigger daily manual |
| `/status` `/portfolio` | NAV, cash, holdings + T+2 countdown |
| *(chat text thường)* | Chat với Claude có context portfolio + tool call |

### MCP server cho Claude Desktop / Cursor / OpenClaw
```bash
vnstock-bot-mcp   # stdio JSON-RPC 2.0 server
```
Expose 5 **read-only** tool: `get_price`, `get_portfolio`, `search_memory`,
`get_timeline`, `recall_similar_decision`. Claude Desktop có thể query
portfolio của bạn mà KHÔNG bao giờ mutate DB.

---

## 🏗️ Kiến trúc highlight

```
┌─────────────────────────────────────────────────────────────┐
│ 1 Python process · asyncio event loop                      │
│                                                             │
│ Telegram ─┐  APScheduler ─┐  MCP stdio ─┐                  │
│           └──────┬────────┴─────────────┘                  │
│                  ▼                                          │
│         Orchestrator (DAG + 6 swarm preset)                │
│           single-agent OR swarm DAG                        │
│                  │                                          │
│  ┌───────┬───────┼───────┬─────────┬────────┬────────┐    │
│  │ 23    │ 5-lyr │ 7     │ Stats   │ Shadow │ Pine   │    │
│  │ skill │ FTS5  │ bias  │ CI +    │ Acct   │ v6     │    │
│  │ rules │ memory│ detect│ lifecyc.│ Δ-PnL  │ export │    │
│  └───────┴───────┴───────┴─────────┴────────┴────────┘    │
│                                                             │
│  State: SQLite + Git (skills/strategy.md) + memory/*.md    │
└─────────────────────────────────────────────────────────────┘
            │                  │                  │
            ▼                  ▼                  ▼
       Telegram API    vnstock (VCI/TCBS)   Claude Agent SDK
```

**218 pytest pass, 0 ruff warning trên toàn bộ code v2.**

Chi tiết topology + data flow: [ARCHITECTURE.md](ARCHITECTURE.md).
Chi tiết cách vận hành từng bước: [OPERATIONS.md](OPERATIONS.md).

---

## 🚀 Cài đặt 5 phút

```bash
# Yêu cầu: Python 3.12 + uv + Claude Code CLI (claude login 1 lần)
cd vnstock-bot

# 1. Install deps
uv sync

# 2. Config — lấy bot token từ @BotFather + chat_id của bạn
cp .env.example .env
# sửa: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_WHITELIST

# 3. DB + warm cache 90 ngày OHLC
uv run vnstock-bot init-db
uv run vnstock-bot warm-cache --days 90

# 4. Smoke test
uv run vnstock-bot doctor
# → ✅ claude-agent-sdk  ✅ vnstock  ✅ DB

# 5. Run (foreground, dùng tmux nếu muốn nền)
uv run vnstock-bot run
```

Sau đó trong Telegram:
```
/start          → verify whitelist
/status         → NAV 100,000,000 VND
/today          → smoke test end-to-end (~5-9 phút cho 25 mã)
/debate FPT     → smoke test swarm DAG
```

Cron 15:30 thứ 2-6 + chủ nhật 10:00 tự chạy — bạn để đó đi làm việc khác.

---

## 📘 Tài liệu

| File | Dành cho ai | Nội dung |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Dev muốn hiểu codebase | Topology, module, boundaries, invariants, schema |
| [OPERATIONS.md](OPERATIONS.md) | Dev đang vận hành / debug | 13 section: daily flow, weekly flow, DAG mechanics, shadow pipeline, failure modes, troubleshooting |
| [skills/README.md](skills/README.md) | Dev muốn thêm skill | Index + meta-rules + frontmatter format |
| [strategy.md](strategy.md) | Bạn (user) | Bài học Claude tự viết qua weekly review — đọc để biết bot đã học gì |
| [.claude/CLAUDE.md](.claude/CLAUDE.md) | Claude Code working on repo | Project guidance, boundaries, invariants |

---

## 🗺️ Roadmap khi bạn mới dùng

| Tuần | Hoạt động | Điều bạn thấy |
|---|---|---|
| 1-2 | Cho bot chạy single mode, xem `/status` mỗi chiều | Bot ra 0-3 decisions/ngày, fills bắt đầu xuất hiện |
| 3-4 | Thử `/debate FPT` + flip `DAILY_RESEARCH_MODE=swarm` | Mọi decision có trace_id, replay được |
| 5-8 | Để cron tự chạy, weekly bắt đầu scoring | `/skills` thấy skill nào uses nhiều |
| 9-12 | Đủ ~30+ scored decisions → lifecycle bắt đầu transition | Weekly message: "🔁 breakout: shadow → active" |
| 12+ | `/report` so Sharpe vs VN-Index | Validate: bot có alpha dương không? |
| Có CSV broker thật | `/shadow upload` CSV | Thấy bạn mất bao nhiêu vì bias |

---

## 🛠️ Dev

```bash
uv run pytest                       # 218 tests
uv run ruff check src tests
uv run ruff format src tests
```

Core invariants (sẽ break nếu bạn đụng vào):
- **Money là `int` VND.** Không `float` trong DB / simulator / validator.
- **No lookahead.** Research agent chỉ thấy data ≤ close hôm nay. Fill ATO phiên sau.
- **T+2 settlement.** `qty_available` ≤ `qty_total`.
- **Biên độ.** ±7% HSX / ±10% HNX / ±15% UPCOM. Validator reject nếu vượt.
- **Statistical gate.** Skill promote chỉ qua `skill_lifecycle.py` — không
  cho phép hand-edit `skill_scores_v2.status` direct.
- **Whitelist chat ID.** 1 user, không multi-tenancy.

Chi tiết: [.claude/CLAUDE.md](.claude/CLAUDE.md).

---

## ❓ Troubleshooting

| Gặp | Làm |
|---|---|
| `/today` không reply | Đợi 5-9 phút (daily research mất lâu với 25 mã watchlist). Check `logs/vnstock-bot.log` |
| `claude-agent-sdk` báo unauth | `claude login` 1 lần rồi restart bot |
| vnstock timeout | Retry `warm-cache`, hoặc bỏ bớt mã yếu thanh khoản khỏi watchlist |
| Message raw markdown trên Telegram | Restart bot — format converter đã ship, cần reload |
| Skill kẹt ở `shadow` mãi | Bình thường cho 6-8 tuần đầu (cần ≥30 scored decisions) |
| DB schema lỗi | `rm data/bot.db*` → `vnstock-bot init-db` (mất state, chỉ dùng nếu test) |

Chi tiết troubleshooting: [OPERATIONS.md §13](OPERATIONS.md#13-troubleshooting-quick-ref).

---

## 💡 Tinh thần dự án

Bot này không cố gắng "làm giàu nhanh". Nó cố gắng **đo lường có kỷ luật**
ra quyết định đầu tư có chất lượng hay không — thứ mà retail trader Việt
Nam hầu như không bao giờ làm.

Sau 3-6 tháng:
- Nếu NAV của bot đánh bại VN-Index với max drawdown thấp hơn → bạn có
  **bằng chứng định lượng** rằng approach của nó có edge → cân nhắc
  áp dụng manual cho tài khoản thật.
- Nếu bot thua → bạn cũng có **bằng chứng định lượng** rằng "gut trading"
  là ảo tưởng, và tiết kiệm được khá nhiều tiền.

Đằng nào cũng lợi. Đó là tinh thần của [PLAN_V2.md](PLAN_V2.md).
