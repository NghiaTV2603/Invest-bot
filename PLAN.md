# vnstock-bot — Kế hoạch dự án

Bot Telegram cá nhân, chạy local, dùng Claude Code Max subscription để research
và giả lập đầu tư chứng khoán Việt Nam. Mục tiêu dài hạn: tự train qua log
quyết định — kết quả, rồi đưa ra lộ trình đầu tư thật tin cậy hơn.

---

## 1. Mục tiêu

### MVP (Phase 1)
- Bot Telegram nhận lệnh, trả lời được câu hỏi về thị trường VN.
- Cron hàng ngày (15:30 GMT+7, sau khi thị trường đóng):
  1. Thu thập dữ liệu: VN-Index, watchlist OHLC, market snapshot, tin.
  2. Claude research theo **skills + playbooks** cố định.
  3. Ghi quyết định vào portfolio giả lập (khớp ATO phiên kế tiếp).
  4. Gửi báo cáo tóm tắt lên Telegram.
- Lưu mọi quyết định + evidence + skills_used vào SQLite để review sau.
- Backtest simulator trên 3–6 tháng dữ liệu lịch sử trước khi chạy live.

### Phase 2 — Tự học có đo lường
- Weekly review job: tính **win-rate per skill** dựa trên `invalidation` đã set.
- Claude cập nhật trực tiếp từng file `skills/*.md` (winner → giữ & mở rộng,
  loser → sửa rule hoặc đánh dấu cần test lại).
- Commit git mỗi lần sửa skill → track evolution của rule-book như codebase.
- Daily research load skills liên quan theo progressive disclosure (không
  nuốt hết vào context).

### Phase 3 — Tư vấn thật
- Bot chỉ **gợi ý**, không tự đặt lệnh. Output: danh mục đề xuất + stop/target.
- So sánh equity curve giả lập với VN-Index. Chỉ chuyển real khi có track-record
  alpha dương ≥ 3 tháng + stable drawdown.

### Phi mục tiêu (rõ ràng KHÔNG làm trong MVP)
- Không kết nối tài khoản CK thật, không đặt lệnh thật.
- Không intraday / HFT. Chỉ swing/position theo ngày.
- Không serve nhiều user — whitelist cứng 1 chat ID.

---

## 2. Tech stack

| Layer | Chọn | Lý do |
|---|---|---|
| Ngôn ngữ | **Python 3.12** | Ổn định với vnstock, pandas, claude-agent-sdk (3.14 quá mới, wheel có thể thiếu) |
| Package mgr | **uv** | Nhanh, lock file rõ; cài `uv` xong `uv sync` là xong |
| LLM | **Claude Agent SDK** (`claude-agent-sdk`) | Dùng session Claude Max sub, không cần API key |
| Telegram | `python-telegram-bot` v21+ | Async, stable nhất |
| Dữ liệu CK | `vnstock` | Nguồn VCI/TCBS/MSN, chuẩn VN |
| DB | **SQLite stdlib** (`sqlite3`) + `schema.sql` + `dataclass` | Không ORM, không Alembic. 4-5 bảng, SQL tay là đủ |
| Số liệu tiền | **`int` VND** hoặc `Decimal` | KHÔNG dùng `float` cho giá/cash (giá FPT ~150k, tránh rounding) |
| Scheduler | **APScheduler** (async) | Cron trong-process; TZ cố định `Asia/Ho_Chi_Minh` |
| Validation | **Pydantic v2** | Schema cho Claude output + config |
| Config | `.env` + `pydantic-settings` | Tách secret ra env |
| Logging | `structlog` | JSON log, dễ grep lịch sử |
| Test | `pytest` + `pytest-asyncio` | Chuẩn |
| Holiday calendar | Hardcode lễ VN + skip T7/CN | Dùng file JSON đơn giản, không cần lib |

> **Claude Agent SDK auth:** Máy đã có `~/.claude/` + Claude Code CLI 2.1.114.
> SDK dùng chung OAuth token của CLI; không cần `ANTHROPIC_API_KEY`.
> Nếu SDK báo unauth → chạy `claude login` 1 lần.

---

## 3. Cấu trúc thư mục

```
vnstock-bot/
├── PLAN.md                          # file này
├── README.md                        # hướng dẫn chạy
├── .env.example                     # TELEGRAM_TOKEN, CHAT_ID_WHITELIST, ...
├── .gitignore
├── pyproject.toml                   # deps + script entrypoint
├── uv.lock
│
├── skills/                          # ⭐ kỹ năng phân tích tái dùng
│   ├── README.md                    # index + meta-rules cho Claude
│   ├── analysis/
│   │   ├── top-down-macro.md        # VN-Index trend, lãi suất, khối ngoại
│   │   ├── sector-rotation.md       # sector nào đang dẫn dắt
│   │   ├── technical-trend.md       # trend, S/R, SMA20/50/200, volume
│   │   ├── technical-momentum.md    # RSI, MACD, breakout rules
│   │   ├── fundamental-screen.md    # P/E, P/B, ROE, EPS growth, D/E
│   │   ├── catalyst-check.md        # KQKD, M&A, cổ tức, room NN
│   │   └── news-triage.md           # nguồn tin tin được, filter noise
│   ├── risk/
│   │   ├── position-sizing.md       # % NAV per trade, Kelly lite
│   │   ├── stop-loss-rules.md       # -8% cứng, trailing stop, time stop
│   │   └── correlation-check.md     # không dồn >2 mã cùng ngành
│   └── playbooks/                   # ⭐ quy trình cho tình huống cụ thể
│       ├── new-entry.md             # 7-bước trước khi BUY mới
│       ├── add-to-winner.md         # pyramiding khi lời ≥10% + xác nhận
│       ├── trim-partial.md          # chốt 1/3 tại +15%, 1/3 tại +25%
│       ├── cut-loser.md             # -8% hoặc thesis sai → cắt
│       └── weekly-review.md         # quy trình chấm điểm + update skills
│
├── src/vnstock_bot/
│   ├── __init__.py
│   ├── main.py                      # entrypoint: Telegram + APScheduler
│   ├── config.py                    # pydantic settings từ .env
│   │
│   ├── telegram/
│   │   ├── bot.py                   # handlers + whitelist chat ID
│   │   └── format.py                # format báo cáo markdown
│   │
│   ├── data/
│   │   ├── vnstock_client.py        # wrap vnstock: OHLC, intraday, BCTC
│   │   ├── market_snapshot.py       # VN-Index, top mover, foreign flow
│   │   ├── news_client.py           # RSS CafeF/VietStock (Phase 2)
│   │   ├── watchlist.py             # load từ config
│   │   ├── holidays.py              # lễ VN + helper is_trading_day()
│   │   └── cache.py                 # parquet cache raw theo ngày
│   │
│   ├── research/
│   │   ├── agent.py                 # gọi Claude Agent SDK
│   │   ├── tools.py                 # tools Claude gọi được
│   │   ├── prompts.py               # system prompt, skill index
│   │   └── skill_loader.py          # load skills/*.md có chọn lọc
│   │
│   ├── portfolio/
│   │   ├── types.py                 # dataclass Holding, Trade, Decision
│   │   ├── simulator.py             # khớp ATO, T+2, phí, biên độ
│   │   ├── validator.py             # Pydantic guard cho mọi proposal
│   │   └── reporter.py              # báo cáo daily/weekly markdown
│   │
│   ├── learning/
│   │   ├── scorer.py                # chấm điểm decision sau 5/10/20 phiên
│   │   ├── skill_scorer.py          # tổng hợp win-rate per skill
│   │   └── weekly_review.py         # weekly job: update skills + git commit
│   │
│   ├── backtest/
│   │   └── runner.py                # replay lịch sử qua simulator
│   │
│   ├── scheduler/
│   │   └── jobs.py                  # daily_research, weekly_review, heartbeat
│   │
│   └── db/
│       ├── schema.sql               # CREATE TABLE ... (source of truth)
│       ├── connection.py            # sqlite3 connect + pragma
│       └── queries.py               # SQL functions (không ORM)
│
├── data/                            # runtime, gitignored
│   ├── bot.db                       # SQLite
│   ├── raw/YYYY-MM-DD.parquet       # raw data dump
│   └── backtest/                    # backtest outputs
├── logs/                            # gitignored
└── tests/
    ├── test_simulator.py            # T+2, ATO, biên độ, phí
    ├── test_validator.py            # reject ticker ngoài watchlist, ...
    ├── test_backtest.py             # replay sanity
    └── test_vnstock_client.py
```

---

## 4. Nguồn dữ liệu

1. **vnstock**: giá EOD, intraday, OHLC, BCTC cơ bản, danh sách mã, ngành.
2. **Market snapshot** mỗi ngày: VN-Index/VN30/HNX OHLC, tổng GTGD, top 5
   tăng/giảm, khối ngoại mua/bán ròng → cho Claude biết bối cảnh vĩ mô.
3. **RSS** (Phase 2): CafeF, VietStock, FireAnt. Claude tool-call khi cần.
4. **Watchlist MVP**: VN-Index + 10–15 mã VN30 (FPT, VNM, HPG, MWG, VCB, TCB,
   ACB, VIC, VHM, MSN, …). Cấu hình trong `config.yaml`.

Luôn dump raw → `data/raw/YYYY-MM-DD.parquet` để replay/backtest.

---

## 5. Thiết kế simulator

### 5.1 Quy tắc khớp lệnh
- Bot ra quyết định sau 15:30 ngày X → order pending cho **ATO ngày X+1**.
- Giá khớp = **giá mở cửa (ATO) ngày X+1** từ vnstock.
- Phí: mua 0.15%, bán 0.15% + thuế TNCN 0.1% = 0.25%.
- Lô tối thiểu 100 cp (HSX), làm tròn xuống.
- Chặn: bán khống, mua vượt cash, mua ngoài biên độ.

### 5.2 Biên độ giá (bắt buộc validate)
| Sàn | Biên độ / phiên thường |
|---|---|
| HSX | ±7% |
| HNX | ±10% |
| UPCOM | ±15% |

Mọi `target_price` và `stop_loss` Claude đề xuất phải nằm trong biên độ.
Validator reject nếu vượt.

### 5.3 T+2 settlement
Mua ngày X → cổ phiếu về tài khoản **cuối ngày X+2** → **bán sớm nhất X+2**
(theo quy định HSX hiện hành). Simulator track `available_qty` vs `total_qty`;
SELL/TRIM chỉ cho phép trên `available_qty`.

### 5.4 Holiday & weekend
`data/holidays.py` chứa dict lễ VN 2026 (Tết, 30/4, 1/5, 2/9, Giỗ Tổ, …).
`is_trading_day(date)` = weekday < 5 AND not in holidays. Cron fire hàng ngày
nhưng job return sớm nếu không phải trading day.

### 5.5 Vốn & sổ sách
- Vốn ảo khởi điểm: **100,000,000 VND** (int, config được).
- Tất cả money stored as **int VND**, không float.
- Bảng SQLite (file `schema.sql`):
  - `holdings(ticker, qty_total, qty_available, avg_cost, opened_at)`
  - `orders(id, decision_id, ticker, side, qty, status, placed_at, filled_at, fill_price, fee)`
  - `decisions(id, created_at, ticker, action, qty, thesis, evidence_json, risks_json, invalidation, skills_used_json, playbook, conviction, source)`
  - `daily_equity(date, cash, market_value, total, vnindex, notes)`
  - `market_snapshot(date, vnindex_ohlc_json, foreign_flow, top_movers_json)`
  - `skill_scores(skill, uses, wins_5d, wins_20d, win_rate_5d, win_rate_20d, last_used)`
  - `decision_outcomes(decision_id, days_held, pnl_pct, thesis_valid, invalidation_hit, scored_at)`

### 5.6 Action types (5 loại)
- `BUY` — mở vị thế mới.
- `ADD` — mua thêm vị thế đang có (pyramiding, yêu cầu playbook `add-to-winner`).
- `TRIM` — bán 1 phần (chốt lời một phần, giảm tỷ trọng).
- `SELL` — bán toàn bộ vị thế.
- `HOLD` — không làm gì, chỉ ghi nhận re-evaluation.

### 5.7 Rủi ro cần guard (hard rules trong simulator)
- 1 mã ≤ 20% NAV.
- ≤ 10 vị thế đồng thời.
- Stop-loss cứng -8% (tính theo close EOD); nếu Claude override phải ghi lý do
  trong `risks_json` và tham chiếu playbook.
- Không quá 2 mã cùng ngành (tính từ sector của vnstock).

---

## 6. Skills & Playbooks

### 6.1 Triết lý
Mọi quyết định phải đi qua quy trình cố định để **đo được cái gì work**.
Không có "Claude cảm thấy FPT tốt" — phải reference skill nào, evidence gì,
điều kiện vô hiệu hóa nào (invalidation).

### 6.2 Format file skill
Mỗi `skills/**/*.md` có frontmatter:

```markdown
---
name: technical-trend
when_to_use: Khi cần xác định trend dài/trung hạn của 1 mã
inputs: [ohlc_60d, volume_60d]
outputs: [trend_direction, support, resistance]
version: 1
---

## Rules
1. Trend UP nếu close > SMA50 > SMA200 ≥ 10 phiên liên tiếp.
2. Support = đáy cục bộ gần nhất có volume > MA20 volume.
3. ...

## Evidence required khi apply
- Giá close hiện tại
- SMA50, SMA200
- Volume trung bình 20 phiên
- ...
```

### 6.3 Progressive disclosure
Agent prompt chỉ chứa `skills/README.md` (index + meta-rules). Claude đọc
index, thấy situation, **tool-call `load_skill(name)`** để pull full content
vào context. Giảm token, tránh overload.

### 6.4 Playbooks = workflow có checklist
Khác skill (tái dùng), playbook là **quy trình cho 1 tình huống**:

```markdown
---
name: new-entry
trigger: Claude muốn BUY một ticker chưa có trong holdings
---

## Checklist (phải PASS hết)
1. [ ] top-down-macro: VN-Index trend không bearish
2. [ ] sector-rotation: ngành của ticker không ở cuối bảng xếp hạng
3. [ ] technical-trend: ticker ở uptrend hoặc breakout
4. [ ] fundamental-screen: ROE ≥ 12%, D/E ≤ 2, EPS growth ≥ 0
5. [ ] catalyst-check: có catalyst trong 30 ngày qua HOẶC kỳ vọng 90 ngày tới
6. [ ] position-sizing: qty không vượt 20% NAV
7. [ ] correlation-check: không quá 2 mã cùng ngành

Fail ≥ 1 checklist → không đề xuất BUY.
```

### 6.5 Skills MVP (v0 — tuần 1)
Chỉ soạn **5 skill + 2 playbook** ban đầu, phần còn lại thêm dần:
- `analysis/top-down-macro.md`
- `analysis/technical-trend.md`
- `analysis/fundamental-screen.md`
- `risk/position-sizing.md`
- `risk/stop-loss-rules.md`
- `playbooks/new-entry.md`
- `playbooks/cut-loser.md`

---

## 7. Decision schema (bắt buộc)

Claude output mỗi proposal phải match Pydantic schema này, validator reject
nếu thiếu field hoặc sai kiểu:

```python
class Decision(BaseModel):
    ticker: str                     # phải ∈ watchlist
    action: Literal["BUY","ADD","TRIM","SELL","HOLD"]
    qty: int                        # bội số 100, >0 trừ HOLD
    target_price: int | None        # VND, trong biên độ
    stop_loss: int | None           # VND, trong biên độ
    thesis: str                     # 1 câu
    evidence: list[str]             # ≥ 3 bullet, phải có số liệu cụ thể
    risks: list[str]                # ≥ 1 bullet
    invalidation: str               # điều kiện khách quan thesis sai
                                    # vd "close < 143,000 sau 2 phiên"
    skills_used: list[str]          # tên skills, ≥ 1
    playbook_used: str | None       # tên playbook
    conviction: int                 # 1-5
```

Có `invalidation` thì learning job mới chấm điểm "thesis đúng/sai" khách quan
sau N ngày.

---

## 8. Claude integration

### 8.1 Daily research agent
- Input tối thiểu (≤ 40k tokens):
  - `skills/README.md` (index)
  - `strategy.md` (bài học chung)
  - watchlist + OHLC 60 ngày
  - holdings hiện tại + cash + pending orders
  - market snapshot hôm nay
  - (optional) tin tức relevant từ news triage
- Tools cấp cho Claude:
  - `load_skill(name)` → return full content skill file
  - `get_price(ticker, days)` → OHLC từ DB
  - `get_news(ticker)` → RSS (Phase 2)
  - `get_fundamentals(ticker)` → BCTC cơ bản từ vnstock
  - `propose_trade(Decision)` → ghi DB sau khi qua validator
- Output: list Decision + tóm tắt Vietnamese cho Telegram.

### 8.2 Chat agent (user nhắn Telegram)
- Same tools + `get_portfolio_status()`.
- Chat history lưu theo thread trong SQLite, giữ 20 tin gần nhất.

### 8.3 Weekly review agent
- Input: tất cả decisions + outcomes 7 ngày + skill_scores + strategy.md.
- Output:
  - Append vào `strategy.md` (bullet ngắn có trích dẫn decision_id).
  - **Sửa trực tiếp skills/*.md** khi win-rate skill thấp (thay đổi rule).
  - Git commit với message format: `skill(<name>): update rule X — win-rate 5d 38%`.

---

## 9. Validation & Observability

### 9.1 Validator layer (bắt buộc)
Mọi `propose_trade` chạy qua chain:
1. Pydantic schema check.
2. Business rules: ticker ∈ watchlist, qty %100, trong biên độ, đủ cash,
   không vượt 20% NAV, không vượt 10 vị thế, sector correlation.
3. Playbook check: nếu `action=BUY` và `playbook=new-entry`, verify checklist
   đã cover trong `evidence`.

Reject nào → log warning + gửi Telegram cuối báo cáo:
`⚠️ 2 proposals rejected: XYZ (ngoài watchlist), ABC (qty không chia hết 100)`.

### 9.2 Observability
- **Heartbeat:** daily job thành công → gửi Telegram 1 dòng xác nhận
  `✅ daily_research OK — 3 decisions, 0 rejected, 12s, ~15k tokens`.
- **Error path:** exception trong job → catch + gửi Telegram
  `❌ daily_research FAILED: vnstock.timeout after 30s` + traceback 10 dòng.
- **Weekly summary Telegram:** cuối chủ nhật gửi skill_scores top/bottom 3.
- Log structlog JSON → `logs/vnstock-bot.log` rotate 7 ngày.

---

## 10. Backtest (bắt buộc trước khi chạy live)

Trước khi bật forward live, chạy backtest để verify logic simulator:

1. Pull OHLC 6 tháng lịch sử cho watchlist.
2. Replay ngày-qua-ngày: với mỗi ngày X, gọi research agent với **chỉ data
   đến X** (không lookahead), record decisions.
3. Simulate fills ATO X+1, T+2, phí đầy đủ.
4. Cuối kỳ: so sánh equity curve vs VN-Index, tính max drawdown, Sharpe đơn giản.
5. **Kiểm tra sanity:**
   - Không có trade nào fill ngoài biên độ.
   - Không có SELL trước T+2.
   - Phí cộng dồn match công thức.
6. Nếu sanity fail → fix simulator trước khi live.
7. Backtest output → `data/backtest/<run_id>/` (equity.csv, trades.csv, report.md).

---

## 11. Lệnh Telegram (MVP)

| Lệnh | Chức năng |
|---|---|
| `/start` | giới thiệu, verify whitelist chat ID |
| `/status` | NAV, cash, P&L hôm nay, vs VN-Index |
| `/portfolio` | holdings + giá vốn + giá hiện tại + % + T+2 countdown |
| `/today` | chạy tay daily_research_job |
| `/decisions 7` | decisions 7 ngày gần nhất (kèm skills_used) |
| `/report week` | báo cáo tuần (equity, win-rate, skill scores) |
| `/skills` | list skills + win-rate hiện tại |
| `/backtest 6mo` | kick backtest 6 tháng (chạy nền, báo khi xong) |
| (text thường) | chat với Claude, có context portfolio |

---

## 12. Roadmap theo tuần

**Tuần 1 — Skeleton, data, skills v0**
- [ ] Setup project: uv init, pyproject, Python 3.12, pre-commit.
- [ ] SQLite schema.sql + connection, dataclass types.
- [ ] vnstock_client: pull OHLC watchlist, market_snapshot.
- [ ] holidays.py + is_trading_day.
- [ ] Telegram bot echo + whitelist chat ID.
- [ ] APScheduler hello-world job mỗi 1 phút.
- [ ] **Soạn 5 skill + 2 playbook v0** (con người viết lần đầu, không Claude).
- [ ] skills/README.md làm index.

**Tuần 2 — Simulator + Claude agent + validator**
- [ ] Simulator: ATO fill, T+2, phí, biên độ, 5 actions, guard rails.
- [ ] Pydantic Decision schema + validator chain.
- [ ] Claude Agent SDK wired up, xác nhận auth qua Max.
- [ ] Tools: load_skill, get_price, get_fundamentals, propose_trade.
- [ ] Daily job end-to-end trên 1 ngày: data → Claude → validator → DB → Telegram.
- [ ] Observability: heartbeat + error-to-Telegram.

**Tuần 3 — Backtest + báo cáo + chat**
- [ ] Backtest runner replay 6 tháng.
- [ ] Fix sanity issues tìm được từ backtest.
- [ ] `/status`, `/portfolio`, `/report week`, `/skills`.
- [ ] Chat agent có context portfolio, history 20 turns.

**Tuần 4 — Learning loop**
- [ ] scorer: chấm decision sau 5/10/20 phiên dựa trên `invalidation`.
- [ ] skill_scorer: aggregate win-rate per skill.
- [ ] weekly_review: Claude sửa trực tiếp skills/*.md + git commit.
- [ ] strategy.md append có trích dẫn decision_id.
- [ ] Dashboard text "equity vs VN-Index" gửi Telegram chủ nhật.

**Sau đó (chỉ khi có track-record 3 tháng alpha dương ổn định):**
- [ ] Mở rộng watchlist.
- [ ] Thêm skills mới (technical-momentum, news-triage, sector-rotation).
- [ ] Chuyển sang mode "tư vấn thật": bot gợi ý, bạn tự đặt lệnh.

---

## 13. Rủi ro & lưu ý

- **vnstock API đổi / rate-limit:** cache raw parquet, có thể fallback nguồn
  khác (TCBS trực tiếp) sau.
- **Claude ảo số liệu:** mọi số trong `evidence` phải đến từ tool-call, không
  để Claude tự bịa. Validator có thể spot-check random 1 số trong evidence
  vs DB.
- **Overfit skills:** weekly review có thể sửa skill sai hướng. Mitigation:
  giới hạn mỗi tuần sửa ≤ 2 skill, commit git để rollback được; skill mới
  cần ≥ 10 uses trước khi tự sửa.
- **Chi phí subscription:** daily ~15k tokens, weekly review ~30k tokens,
  chat rời rạc — well within Max 200 quota.
- **Timezone:** `Asia/Ho_Chi_Minh`, APScheduler config TZ rõ ràng.
- **Secret:** `.env` không commit; `.gitignore` chặn `data/`, `logs/`, `.env`.
- **Disclaimer:** README ghi rõ "bot cá nhân, không phải lời khuyên đầu tư".
- **Holiday miss:** lễ VN có thể thay đổi, check đầu năm update `holidays.py`.
- **T+2 có thể đổi chính sách:** hiện T+2, nếu HSX đổi T+1/T+0 phải update
  simulator constant.

---

## 14. Setup checklist (khi start code)

- [ ] `uv init` + pin Python 3.12.
- [ ] `.env` với `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID_WHITELIST`,
  `INITIAL_CAPITAL_VND=100000000`, `TZ=Asia/Ho_Chi_Minh`.
- [ ] Tạo bot trên `@BotFather`, lưu token vào `.env`.
- [ ] Xác nhận `claude login` OK (hoặc SDK pick up session từ CLI).
- [ ] `git init` trong `vnstock-bot/`, first commit PLAN.md + skills v0.
- [ ] Tạo Telegram group riêng bạn + bot, lấy chat_id.
