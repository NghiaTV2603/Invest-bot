---
name: technical-trend
version: 1
status: active
category: analysis
when_to_use: Xác định trend, support/resistance, momentum cho 1 ticker
inputs: [ohlc_60d, volume_60d]
outputs: [trend_direction, support, resistance, breakout_signal]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Trả lời: mã này đang **uptrend / sideway / downtrend**, đâu là
support/resistance gần nhất, có breakout không.

## Rules

### R1. Trend theo SMA
- SMA20, SMA50, SMA200 tính theo close.
- **UPTREND**: close > SMA20 > SMA50 > SMA200.
- **DOWNTREND**: close < SMA20 < SMA50 < SMA200.
- **SIDEWAY**: các MA quấn nhau, khoảng cách < 2%.

### R2. Support & resistance
- **Support**: đáy cục bộ gần nhất trong 40 phiên, đồng thời có volume >= MA20 volume.
- **Resistance**: đỉnh cục bộ gần nhất trong 40 phiên, volume >= MA20 volume.
- Ghi rõ **2 level S + 2 level R** gần giá hiện tại nhất.

### R3. Breakout signal
- **BREAKOUT UP**: close > resistance gần nhất, volume ngày breakout ≥ 1.5 × MA20 volume.
- **BREAKDOWN**: close < support gần nhất, volume ≥ 1.3 × MA20 volume.
- Breakout không có volume → tín hiệu yếu, giảm conviction 1 bậc.

### R4. Volume dry-up
- Volume 5 phiên gần nhất < 50% MA20 volume → thị trường "chán",
  không BUY dù giá đẹp.

### R5. Giá so với biên độ 60 phiên
- % từ đáy 60 phiên và % từ đỉnh 60 phiên.
- Gần đáy (bottom 20%) + uptrend short-term → entry tốt.
- Gần đỉnh (top 10%) → cẩn trọng, confirm bằng volume.

## Evidence required
- Close hôm nay
- SMA20, SMA50, SMA200
- MA20 volume + volume 5 phiên gần nhất
- 2 support + 2 resistance (giá cụ thể)
- % từ đáy/đỉnh 60 phiên
- Breakout signal nếu có (với date + volume ratio)

## Không làm
- Không dùng indicator > 200 phiên lịch sử (mã VN ít data lâu).
- Không kết luận "support/resistance mạnh" mà không cite volume.
