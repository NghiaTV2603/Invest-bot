---
name: mean-reversion
version: 1
status: active
category: strategy
when_to_use: Bắt đáy cục bộ khi Z-score + RSI cho tín hiệu oversold trong uptrend dài hạn
inputs: [ohlc_60d]
outputs: [zscore, rsi, mean_reversion_score]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Entry **ngược với momentum ngắn hạn** khi giá lệch quá xa mean và mã vẫn
đang trong uptrend trung hạn. Đối ngược với `breakout` / `momentum`.

## Thông số

- Z-score lookback: **20 phiên**.
- RSI period: **14**.
- Long-term trend filter: **SMA50** (bắt buộc).

## Core formula

```
zscore = (close - SMA20) / stdev(close, 20)
```

## Rules

### R1. Hard gate — phải trong uptrend trung hạn
- Close > SMA50 bắt buộc. Nếu dưới SMA50 → **không trade mean-reversion**, dễ
  catching falling knife.

### R2. Detect oversold setup
Signal entry khi **TOÀN BỘ** đúng:
- `zscore ≤ -2.0` (giá 2 độ lệch chuẩn dưới mean 20 ngày).
- `RSI ≤ 30` (oversold).
- Ngày hôm sau close > close ngày hit oversold **ít nhất 1 phiên** (confirm bật).
- Volume ngày entry ≥ 0.8 × MA20 (volume không quá yếu).

### R3. Mean-reversion score

```
score = zscore_component + rsi_component + trend_component
      ∈ [-2, +3]
```

| Component | +2 | +1 | 0 | -1 |
|---|---|---|---|---|
| z-score | ≤ -2.5 | -2.0 to -2.5 | -1.5 to -2.0 | > -1.5 |
| RSI | ≤ 25 | 25-30 | 30-40 | > 40 |
| Trend (close vs SMA50) | — | > SMA50 + SMA50 up | > SMA50 flat | < SMA50 |

- `score ≥ +3` → BUY eligible, stop chặt.
- `+1..+2` → watching.
- `≤ 0` → không trade.

### R4. Entry + stop + target
- Entry: close ngày confirm (R2 bật lên).
- Stop: dưới low của ngày Z-score thấp nhất − 2%.
- Target: **SMA20** hoặc **zscore = 0** — cái nào gần hơn. Conservative.
- Target 2 (nếu tiếp tục đẹp): +1.5 × risk.

### R5. Time stop
- Nếu **không reach SMA20 trong 7 phiên** → exit, dù chưa lỗ.
- Mean-reversion có time horizon ngắn (≤ 10 phiên). Hold lâu hơn = thesis sai.

## Evidence required

- Z-score hiện tại + 5 phiên gần nhất
- RSI hiện tại + thấp nhất trong setup
- SMA50 + hướng (up/flat/down)
- Close ngày confirm + volume ngày đó
- Entry, stop, target cụ thể (VND int)

## Không làm

- Không entry mean-reversion trên mã downtrend (close < SMA50). Rule R1 hard.
- Không add vào loser "vì Z-score tệ hơn" — đây là cách tự đào hố.
- Không hold vượt time stop — mean-reversion fail fast.
