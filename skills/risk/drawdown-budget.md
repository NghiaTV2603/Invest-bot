---
name: drawdown-budget
version: 1
status: active
category: risk
when_to_use: Kiểm soát portfolio-level drawdown — tự động de-risk khi NAV rơi quá mức cho phép
inputs: [daily_equity_120d, current_nav, gross_exposure]
outputs: [dd_pct, de_risk_action, max_allowed_gross]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Khi portfolio NAV rơi, **bót tay trước khi quá muộn**. Rule-based throttling
thay vì để cảm xúc cắt hay giữ.

## Công thức drawdown

```
peak_nav_120d = max(nav_t  for t in last 120 days)
drawdown_pct  = (current_nav - peak_nav_120d) / peak_nav_120d
```

*Sử dụng peak 120 ngày, không all-time. Sau 6 tháng recovery peak reset.*

## Thresholds & action

| DD pct | Action | Max gross exposure |
|---|---|---|
| 0 to -5% | Normal | 100% NAV |
| -5% to -10% | Caution, không BUY mới bình thường | 90% NAV |
| -10% to -15% | **De-risk nhẹ**: TRIM 20% mã yếu nhất | 80% NAV |
| -15% to -20% | **De-risk mạnh**: cắt 50% weakest, không BUY | 60% NAV |
| < -20% | **Circuit breaker**: all-cash mode, review toàn bộ thesis | 30% NAV |

## Rules

### R1. Detect drawdown
- Tính DD mỗi EOD.
- Lưu vào DB (daily_equity) — dùng để replay, không recompute mỗi call.

### R2. Weakest mã
Khi cần TRIM, xác định "yếu nhất" qua:
```
weakness = -return_20d_of_ticker
        + (thesis_invalidation_proximity)
        + (sector_is_lagging?)
```
- Mã có return 20d tệ nhất + thesis đã break + sector lagging → TRIM trước.
- Nếu không có mã "yếu rõ", TRIM theo pro-rata.

### R3. Circuit breaker (DD < -20%)
- **All-cash mode**: đưa gross exposure về ≤ 30% NAV.
- **Stop trading**: không BUY mới trong 10 phiên.
- **Post-mortem**: weekly review bắt buộc phân tích nguyên nhân DD:
  skill nào gây lỗ, bias nào dính, macro nào miss.
- Rollout lại từ từ: mỗi tuần thêm 10% exposure nếu NAV ổn định (không DD thêm).

### R4. Recovery rule
- Khi NAV recovery lên 95% peak → reset DD tracker, được BUY bình thường.
- Không ngay lập tức "gồng" 100% gross — ease back.

### R5. Daily DD (intraday floor)
- Nếu NAV hôm nay rơi > 5% trong 1 phiên → alert Telegram, dừng mọi decision
  tự động trong 24h, chờ human review.

## Evidence required

- NAV hiện tại + peak 120d + % DD
- Gross exposure hiện tại + max cho phép theo bảng
- Nếu action = TRIM: list mã + lý do "yếu nhất"
- Nếu circuit breaker: flag explicit, ghi vào event kind='observation'

## Kết hợp với action

- Trước mọi `propose_trade(BUY/ADD)`: check gross_exposure + DD budget.
  Nếu BUY vi phạm max allowed → reject kể cả thesis đẹp.
- SELL/TRIM **không bị** drawdown-budget chặn (chỉ giảm risk, không tăng).

## Không làm

- Không "gồng" qua -20% với hy vọng. Circuit breaker là hard rule.
- Không reset peak NAV tùy tiện. Chỉ reset khi > 120 ngày hoặc recovery ≥ 95%.
- Không override bằng "mã này sắp bật". Đó là bias — de-risk trước, re-enter sau.
