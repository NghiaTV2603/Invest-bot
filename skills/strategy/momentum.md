---
name: momentum
version: 1
status: active
category: strategy
when_to_use: Xác nhận momentum mạnh cho entry BUY/ADD — combine RSI + MACD + volume
inputs: [ohlc_60d]
outputs: [momentum_score, rsi, macd_histogram, volume_ratio]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Đo đà (momentum) ngắn-trung hạn qua 3 chỉ báo cộng hưởng: RSI, MACD
histogram, volume.

## Thông số

- RSI period: **14**
- MACD: fast=12, slow=26, signal=9
- Volume MA: **20**

## Rules

### R1. RSI regime
- **RSI > 70**: overbought — KHÔNG entry mới, cân nhắc TRIM.
- **55 ≤ RSI ≤ 70**: momentum up mạnh, eligible entry với trend + volume.
- **45 ≤ RSI < 55**: neutral, chờ.
- **30 ≤ RSI < 45**: weak, watching cho reversal.
- **RSI < 30**: oversold — không entry momentum, chuyển dùng `mean-reversion`.

### R2. MACD histogram
- **Histogram > 0 VÀ đang tăng ≥ 3 phiên** → confirm bull momentum.
- **Histogram < 0 VÀ đang giảm ≥ 3 phiên** → confirm bear momentum.
- MACD cross over signal line = signal bổ sung (không đủ riêng).

### R3. Volume confirm
- **Bullish momentum** cần volume hôm nay ≥ **1.5 × MA20 volume**.
- Volume thấp hơn → momentum yếu, score × 0.5.
- Volume < MA20 trong uptrend = **distribution warning** (institutional bán).

### R4. Momentum score

```
score = rsi_component + macd_component + volume_component
       ∈ [-3, +3]
```

| Component | Giá trị |
|---|---|
| RSI | +1 nếu 55-70 up; 0 nếu 45-55; -1 nếu <45; -2 nếu >70 |
| MACD histogram | +1 nếu >0 & rising 3d; -1 nếu <0 & falling 3d |
| Volume | +1 nếu ≥1.5×MA20; -1 nếu <MA20 trong uptrend |

- `score ≥ +2` → entry eligible.
- `-1 ≤ score ≤ +1` → HOLD.
- `score ≤ -2` → SELL/TRIM consider.

### R5. Divergence detection (signal mạnh, rare)
- **Bearish divergence**: giá tạo đỉnh cao hơn nhưng RSI tạo đỉnh thấp hơn → warning.
- **Bullish divergence**: giá tạo đáy thấp hơn nhưng RSI tạo đáy cao hơn → reversal possible.
- Divergence override momentum score 1 bậc về hướng divergence.

## Evidence required

- RSI hiện tại + trung bình 5 phiên
- MACD line + signal + histogram (cụ thể, không chỉ "MACD positive")
- Volume hôm nay + MA20 volume + tỷ số
- % giá 20 phiên (để biết đã chạy bao xa)

## Không làm

- Không chỉ dựa RSI — RSI có thể "stuck" ở overbought hàng tuần trong uptrend mạnh.
- Không entry momentum trong sideway regime (`top-down-macro` = SIDEWAY).
- Không chase: nếu giá đã +15% trong 5 phiên, momentum cao nhưng R:R kém.
