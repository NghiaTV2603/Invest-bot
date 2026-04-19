---
name: ichimoku
version: 1
status: active
category: strategy
when_to_use: Xác định trend mạnh + entry/exit qua Kumo cloud + Tenkan/Kijun cross
inputs: [ohlc_60d]
outputs: [ichimoku_signal, kumo_direction, cross_type]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Sử dụng Ichimoku Kinko Hyo — một hệ thống hoàn chỉnh về trend, momentum,
support/resistance.

## Thông số

| Line | Công thức | Period |
|---|---|---|
| Tenkan-sen (conversion) | (high + low) / 2 trên 9 phiên | 9 |
| Kijun-sen (base) | (high + low) / 2 trên 26 phiên | 26 |
| Senkou Span A (cloud top) | (Tenkan + Kijun) / 2 shift 26 | — |
| Senkou Span B (cloud bot) | (high + low) / 2 trên 52, shift 26 | 52 |
| Chikou Span (lagging) | close shift back 26 | — |

*Cho VN market (EOD) có thể giảm xuống 9/26/52 phiên giao dịch ~ 2.5 tháng.*

## Rules

### R1. Kumo regime
- Close **trên cloud** (Span A & B) → **bullish regime**.
- Close **dưới cloud** → **bearish regime**.
- Close **trong cloud** → **neutral / sideway**, không entry.
- Cloud xanh (Span A > Span B) → momentum bull. Cloud đỏ → bear.
- Cloud mỏng (Span A gần Span B) → regime có thể đổi.

### R2. Tenkan/Kijun cross
- **Golden cross**: Tenkan cắt lên Kijun **trên cloud** → bull mạnh (+2).
- **Golden cross trong/dưới cloud** → bull yếu (+1), cần confirm.
- **Dead cross**: Tenkan cắt xuống Kijun **dưới cloud** → bear mạnh (-2).
- **Dead cross trên/trong cloud** → bear yếu (-1).

### R3. Chikou confirm
- Chikou (close today) nằm **trên giá 26 phiên trước** → confirm bull.
- Chikou dưới giá 26 phiên trước → confirm bear.
- Chikou đi qua vùng giá cũ (chạm resistance quá khứ) → cản trở.

### R4. Kijun as trailing support
- Trong bullish regime: Kijun là **trailing stop động**.
- Close đóng dưới Kijun + không hồi phục 2 phiên → signal exit.

### R5. Tổng hợp signal
```
score = kumo_regime(-2/0/+2) + cross_type(-2..+2) + chikou(-1/0/+1)
```
- `score ≥ +3` → strong bull, BUY eligible.
- `score ≤ -3` → strong bear, SELL/avoid.
- `-2 < score < +2` → trung lập, không entry.

## Evidence required

- Close hôm nay + Span A + Span B (biết giá đang ở đâu vs cloud)
- Tenkan + Kijun + ngày cross gần nhất
- Chikou vs giá 26 phiên trước
- Cloud color + độ dày (Span A - Span B)

## Không làm

- Không apply trên mã thanh khoản thấp (ADV20 < 500k) — tín hiệu noise.
- Không chỉ dùng Tenkan/Kijun cross mà bỏ Kumo — cross trong cloud rất hay fail.
