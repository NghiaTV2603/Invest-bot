---
name: candlestick
version: 1
status: active
category: strategy
when_to_use: Xác nhận entry/exit signal qua 15 pattern candlestick (port từ Vibe-Trading)
inputs: [ohlc_20d]
outputs: [pattern_detected, direction, compound_score]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Detect 15 pattern nến kinh điển bằng quy tắc vectorized (port từ
Vibe-Trading). Output `compound_score ∈ [-3, +3]` — bullish > 0, bearish < 0.
Ra vào lệnh **KHÔNG chỉ dựa candlestick** — phải combine với trend +
volume + level.

## Thresholds (tunable)

- `body_pct`: thân nến / tổng range. Doji: body_pct < 0.1. Marubozu: > 0.8.
- `shadow_ratio`: min shadow length / body length. Hammer: lower_shadow ≥ 2×body.
- Volume confirm: pattern trong ngày volume ≥ MA20(volume) × 1.2 → tăng độ tin cậy.

## 15 patterns

### Single-candle (5)

| # | Pattern | Rule ngắn | Signal |
|---|---|---|---|
| 1 | **Hammer** | Ở downtrend; lower_shadow ≥ 2×body; upper_shadow ≤ 0.3×body; close > mid | +1 bull |
| 2 | **Inverted Hammer** | Ở downtrend; upper_shadow ≥ 2×body; lower_shadow ≤ 0.3×body | +1 bull (yếu) |
| 3 | **Shooting Star** | Ở uptrend; upper_shadow ≥ 2×body; lower_shadow ≤ 0.3×body; close < mid | -1 bear |
| 4 | **Doji** | body_pct < 0.1; upper + lower shadow ≈ nhau | 0 reversal pending |
| 5 | **Spinning Top** | body_pct < 0.3; shadow 2 đầu tương đương > body | 0 indecision |

### Double-candle (5)

| # | Pattern | Rule ngắn | Signal |
|---|---|---|---|
| 6 | **Bullish Engulfing** | Nến 1 đỏ, nến 2 xanh; body 2 bao trùm body 1 | +2 bull mạnh |
| 7 | **Bearish Engulfing** | Nến 1 xanh, nến 2 đỏ; body 2 bao trùm body 1 | -2 bear mạnh |
| 8 | **Bullish Harami** | Nến 1 đỏ dài; nến 2 xanh nhỏ lọt trong body 1 | +1 bull |
| 9 | **Piercing Line** | Nến 1 đỏ; nến 2 mở < close 1, đóng > mid body 1 | +1 bull |
| 10 | **Dark Cloud Cover** | Nến 1 xanh; nến 2 mở > high 1, đóng < mid body 1 | -1 bear |

### Triple-candle (5)

| # | Pattern | Rule ngắn | Signal |
|---|---|---|---|
| 11 | **Morning Star** | Nến 1 đỏ dài; nến 2 doji/nhỏ gap xuống; nến 3 xanh đóng > mid body 1 | +3 bull |
| 12 | **Evening Star** | Nến 1 xanh dài; nến 2 doji/nhỏ gap lên; nến 3 đỏ đóng < mid body 1 | -3 bear |
| 13 | **Three White Soldiers** | 3 nến xanh liên tiếp, mỗi nến open trong body trước, close > close trước | +2 bull |
| 14 | **Three Black Crows** | 3 nến đỏ liên tiếp, mỗi nến open trong body trước, close < close trước | -2 bear |
| 15 | **Inside Bar** | Nến 2 nằm lọt trong range nến 1 | 0 wait breakout |

## Rules apply

### R1. Compound score
`compound = sum(signals các pattern detect được trên 3 nến gần nhất)`
Clip về [-3, +3].

### R2. Context filter (tránh false positive)
- Bullish reversal (Hammer, Morning Star, Bull Engulfing) **chỉ đếm** nếu ở
  downtrend (SMA20 dốc xuống ≥ 3 phiên).
- Bearish reversal **chỉ đếm** nếu ở uptrend.
- Continuation pattern (3 Soldiers/Crows) cần đi cùng trend.

### R3. Volume confirm
Nếu volume pattern day ≥ 1.5 × MA20 → nhân signal × 1.5 (rồi clip).
Nếu volume < 0.5 × MA20 → nhân × 0.5 (tín hiệu yếu).

### R4. Kết hợp hành động
- `compound ≥ +2` + uptrend + volume OK → entry/ADD eligible.
- `compound ≤ -2` + holding → TRIM hoặc SELL eligible (vẫn cần confirm từ
  `top-down-macro` + `stop-loss-rules`).
- Pattern riêng **không đủ** để BUY — phải kết hợp skill khác.

## Evidence required

- 3 nến gần nhất (O/H/L/C/V)
- Pattern name detected
- `body_pct` + `shadow_ratio` cụ thể
- Volume vs MA20 volume
- Context trend (từ `technical-trend`)

## Không làm

- Không đếm pattern ở vùng sideway chặt (SMA20 flat < 1%/tuần).
- Không dùng candlestick đơn lẻ cho quyết định > 20% NAV.
