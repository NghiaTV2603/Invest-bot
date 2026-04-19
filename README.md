# vnstock-bot

> Telegram bot cá nhân giả lập đầu tư chứng khoán Việt Nam, có kỷ luật thống
> kê: mỗi skill có bootstrap CI + walk-forward, swarm DAG tranh luận trước
> khi chốt BUY, 7 bias detector tự kiểm tra, và Shadow Account để đối chiếu
> với trade thật qua CSV broker.

> ⚠️ **Disclaimer:** Bot cá nhân, chạy local, **không phải lời khuyên đầu tư**.
> Mọi quyết định là của bạn.

---

## Bot này làm được gì

### Hằng ngày (15:30 GMT+7, thứ 2-6)
- Snapshot thị trường (VN-Index, khối ngoại, top movers)
- Fill orders pending phiên hôm trước (ATO + T+2 + phí 0.25%)
- Kiểm tra stop-loss → tự đề xuất SELL nếu vượt -8%
- Research watchlist qua Claude — đi theo **skills** có quy tắc rõ + có thể
  kích **swarm bull↔bear** cho mỗi BUY mới (`DAILY_RESEARCH_MODE=swarm`)
- Validate mọi proposal (Pydantic + biên độ + position cap) trước khi ghi DB
- Gửi báo cáo Telegram với decision_id + trace_id để replay được

### Hằng tuần (chủ nhật 10:00)
- Chấm điểm decisions 5/10/20 phiên qua invalidation
- **Compute bootstrap CI + walk-forward per skill** (unblock skill lifecycle)
- **Bias self-check** trên decisions 90d — 7 loại: disposition, overtrading,
  chase_momentum, anchoring, hot_hand, skill_dogma, recency
- **Skill lifecycle FSM**: draft → shadow → active → archived theo stat gate
  (≥30 uses, CI95_low > 0.5, walk-forward pass ≥3/5)
- **L4 pattern extraction** từ winning decisions → skill_proposer gợi draft mới
- Claude có thể sửa rule trong `skills/*.md` → git commit tự động

### Ad-hoc (Telegram)
- Chat thường có context portfolio
- `/debate <ticker>` — bull↔bear swarm tranh luận trước BUY
- `/review <ticker>` — swarm review holding (fundamental + technical + invalidation)
- `/shadow upload` → gửi CSV broker → HTML report 8-section Delta-PnL
- `/bias` — grid bias severity của bot
- `/why <trace_id>` hoặc `/why d<decision_id>` — replay DAG node-by-node
- `/recall <ticker>` — timeline + decision cũ
- `/regime` — label regime gần nhất từ `macro_sector_desk` swarm
- `/skill status <name>` / `/skill promote <draft>` — xem CI, promote draft
- `/export pine <template>` — sinh Pine Script v6 cho TradingView
- `/backtest <months>` — replay lịch sử qua simulator

### MCP server (Claude Desktop / Cursor / OpenClaw)
```bash
vnstock-bot-mcp   # stdio JSON-RPC server
```
Expose 5 **read-only** tool: `get_price`, `get_portfolio`, `search_memory`,
`get_timeline`, `recall_similar_decision`. KHÔNG bao giờ write DB.

---

## Cài đặt

**Yêu cầu:**
- Python **3.12**
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) package manager
- Claude Code CLI (`claude login` 1 lần — SDK chia sẻ token, không cần API key)
- Telegram bot token từ [@BotFather](https://t.me/BotFather)

```bash
cd vnstock-bot

# 1. Cài dependencies
uv sync

# 2. Config
cp .env.example .env
# mở .env, điền TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_WHITELIST

# 3. Khởi tạo DB (schema + defensive migration)
uv run vnstock-bot init-db

# 4. Smoke test (verify SDK + vnstock + DB)
uv run vnstock-bot doctor

# 5. Warm OHLC cache (optional — nhanh daily research lần đầu)
uv run vnstock-bot warm-cache --days 90
```

## Chạy

```bash
# foreground — xem log trực tiếp
uv run vnstock-bot run

# background (macOS) — dùng tmux tạm thời
tmux new -s vnbot 'uv run vnstock-bot run'
# detach: Ctrl+B, D ; attach lại: tmux attach -t vnbot
```

Mặc định bot sẽ:
- Long-poll Telegram
- Cron 15:30 GMT+7 thứ 2-6 → `daily_research_job`
- Cron chủ nhật 10:00 → `weekly_review_job`

### Mode chọn (env `.env`)

| Env | Giá trị | Ý nghĩa |
|---|---|---|
| `DAILY_RESEARCH_MODE` | `single` (default) / `swarm` | Single-agent (v1) hay orchestrator DAG |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Model dùng cho Claude SDK |
| `CLAUDE_DAILY_TOKEN_BUDGET` | `40000` | Soft budget cho daily research |
| `INITIAL_CAPITAL_VND` | `100000000` | Vốn ảo khởi điểm |
| `TELEGRAM_CHAT_ID_WHITELIST` | comma-sep | Chỉ chat ID này mới dùng được bot |

---

## Lệnh CLI

```bash
uv run vnstock-bot run               # start bot + scheduler
uv run vnstock-bot doctor            # health check
uv run vnstock-bot init-db           # tạo schema
uv run vnstock-bot today             # chạy manual 1 daily (no Telegram)
uv run vnstock-bot warm-cache --days 90   # pull OHLC 90 ngày vào cache
uv run vnstock-bot backtest --months 6    # replay 6 tháng
uv run vnstock-bot-mcp               # stdio MCP server
```

## Lệnh Telegram đầy đủ

| Lệnh | Chức năng |
|---|---|
| `/start` | Verify chat ID + list commands |
| `/status`, `/portfolio` | NAV, cash, holdings + T+2 countdown |
| `/today` | Chạy manual daily research |
| `/today_swarm` | Force swarm daily (bypass `DAILY_RESEARCH_MODE`) |
| `/decisions 7` | Decisions 7 ngày gần nhất |
| `/report` | Weekly NAV vs VN-Index (alpha) |
| `/backtest 6` | Backtest 6 tháng (nền) |
| `/skills` | List skills + win-rate |
| `/skill status <name>` | Version, status, CI95, walk-forward |
| `/skill promote <name>` | Approve draft → shadow |
| `/debate <ticker>` | Bull↔Bear swarm |
| `/review <ticker>` | Position review swarm |
| `/shadow upload` | Hướng dẫn upload CSV broker |
| `/shadow report` | List 5 shadow gần nhất |
| *(attach `.csv`)* | Auto parse + extract rule + HTML 8-section |
| `/bias` | 7 bias detector trên bot decisions |
| `/recall <ticker>` | Timeline + decisions cũ |
| `/why <trace_id\|d42>` | Replay DAG node-by-node |
| `/regime` | Regime label gần nhất |
| `/export pine <template>` | Pine Script v6 (breakout/ma_cross/rsi_mr/ichimoku/mf_screen) |
| *(text thường)* | Chat với Claude có context portfolio |

---

## Cấu trúc dự án (tổng quan)

```
vnstock-bot/
├── src/vnstock_bot/
│   ├── main.py                    # CLI entry + APScheduler
│   ├── config.py                  # pydantic-settings từ .env
│   ├── telegram/                  # bot handlers + v2 commands
│   ├── scheduler/                 # daily_research + weekly_review jobs
│   ├── orchestrator/              # async DAG runner + preset loader
│   ├── research/                  # Claude Agent SDK wrapper + tools
│   ├── memory/                    # 5-layer + FTS5 + patterns
│   ├── skills/*                   # (at repo root) rule-book markdown
│   ├── bias/                      # 7 bias detector
│   ├── learning/                  # stats, lifecycle, proposer, weekly_review
│   ├── shadow/                    # broker parsers + Delta-PnL + HTML
│   ├── portfolio/                 # simulator (ATO/T+2) + validator + reporter
│   ├── backtest/                  # runner + metrics + optimizers + validation
│   ├── export/                    # Pine Script generator
│   ├── mcp/                       # stdio MCP server
│   ├── data/                      # vnstock wrapper + watchlist + holidays
│   └── db/                        # schema.sql + connection + queries
├── skills/                        # 25+ rule-book skills + playbooks
├── config/
│   ├── watchlist.yaml             # mã quan tâm + sector
│   └── swarm/*.yaml               # 6 swarm preset (DAG definition)
├── data/                          # runtime, gitignored
│   ├── bot.db                     # SQLite state
│   ├── raw/                       # parquet cache
│   ├── shadow/                    # user broker uploads
│   ├── reports/                   # HTML shadow reports
│   ├── export/pine/               # generated Pine scripts
│   ├── memory/                    # 5-layer memory files
│   └── backtest/                  # backtest outputs
├── tests/                         # 205 pytest
├── skills/                        # rule-book (analysis/strategy/risk/flow/tool/playbooks)
└── strategy.md                    # bài học tự viết qua weekly review
```

## Dev

```bash
uv run pytest                       # 205 tests
uv run ruff check src tests
uv run ruff format src tests
```

---

## Tài liệu

| File | Nội dung |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Kiến trúc — module, data flow, boundaries, schema |
| [OPERATIONS.md](OPERATIONS.md) | Vận hành chi tiết — từ cron đến decision đến lifecycle |
| [skills/README.md](skills/README.md) | Index skills + meta-rules cho Claude |
| [strategy.md](strategy.md) | Bài học Claude tự viết qua weekly review |
| [.claude/CLAUDE.md](.claude/CLAUDE.md) | Project guidance cho Claude Code |

## Troubleshooting

- **`claude-agent-sdk` báo unauthenticated** — chạy `claude login` 1 lần.
- **vnstock timeout** — retry hoặc kiểm tra mạng; có parquet cache fallback.
- **Bot không reply** — verify `TELEGRAM_CHAT_ID_WHITELIST` match `chat.id`
  của bạn. Có thể lấy chat_id bằng cách nhắn bot rồi xem `logs/vnstock-bot.log`.
- **Swarm DAG timeout** — rollback về single-agent qua
  `DAILY_RESEARCH_MODE=single`, xem `trace_id` qua `/why`.
- **Reset sạch** — xóa `data/bot.db` + `data/raw/` → `uv run vnstock-bot init-db`.
# Invest-bot
