---
name: smc
version: 1
status: active
category: strategy
when_to_use: Xác định structure break + order block + FVG để entry có timing tốt hơn
inputs: [ohlc_60d]
outputs: [bos_detected, choch_detected, fvg_zones, order_blocks]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Smart Money Concepts — nhìn cấu trúc thị trường qua **swing point**, **BOS**
(break of structure), **ChoCH** (change of character), **FVG** (fair value
gap), **Order Block**. Dùng để xác nhận trend flip + entry zone chính xác hơn
chỉ SMA cross.

## Thông số

- `swing_length = 10` — cần N nến bên trái + bên phải để xác nhận swing high/low.
- `close_break = True` — chỉ tính break khi **close** phá mức, không chỉ high/low.

## Khái niệm

### Swing high / swing low
- **Swing High**: high nến X > high của N nến trái và N nến phải.
- **Swing Low**: low nến X < low của N nến trái và N nến phải.

### BOS (Break of Structure) — trend continuation
- **Bullish BOS**: close > swing_high gần nhất trong uptrend → trend tiếp tục.
- **Bearish BOS**: close < swing_low gần nhất trong downtrend → tiếp tục giảm.

### ChoCH (Change of Character) — trend reversal
- **Bullish ChoCH**: đang downtrend, close break lên swing_high → dấu hiệu flip bull.
- **Bearish ChoCH**: đang uptrend, close break xuống swing_low → dấu hiệu flip bear.
- ChoCH **mạnh hơn** BOS vì báo trend thay đổi.

### FVG (Fair Value Gap) — 3-bar imbalance
- **Bullish FVG**: low của bar 3 > high của bar 1 (có gap giữa bar 2 và 1-3).
- **Bearish FVG**: high của bar 3 < low của bar 1.
- **FVG là vùng giá thường được fill** khi price quay lại — entry zone.

### Order Block — institutional footprint
- **Bullish OB**: **nến giảm cuối cùng** trước 1 bullish BOS. Vùng giá nến này
  là support mạnh.
- **Bearish OB**: nến tăng cuối cùng trước 1 bearish BOS. Resistance mạnh.

## Rules apply

### R1. Bullish setup
1. Phát hiện **bullish ChoCH** trên biểu đồ → trend flip bull.
2. Chờ price pullback về **bullish FVG** hoặc **bullish OB**.
3. Entry trong zone đó + stop dưới swing_low.
4. Target = swing_high tiếp theo hoặc +1.5×risk.

### R2. Bearish setup (short / exit long)
- Ngược lại R1. Trong portfolio VN chỉ long → dùng để **TRIM/SELL** khi
  bearish ChoCH + price break swing_low.

### R3. Confluence required
Signal SMC **đơn độc không đủ**. Phải cộng hưởng với:
- `technical-trend` (SMA align)
- `volume` (BOS/ChoCH có volume ≥ 1.3 × MA20)
- Một trong các skill analysis (`top-down-macro`, `catalyst-check`)

### R4. Risk sizing
- SMC entry thường có stop chặt (1-3% giá). Phù hợp conviction 4-5 + position
  sizing Kelly-lite.

## Evidence required

- Swing high / swing low gần nhất (ngày + giá)
- BOS hay ChoCH detect (loại + ngày)
- FVG zones detected (price range)
- Order block zone gần nhất
- Volume ngày BOS/ChoCH

## Không làm

- Không dùng SMC cho mã thanh khoản thấp (ADV20 < 500k) — swing point không đủ tin cậy.
- Không entry ngay ở BOS — chờ pullback về FVG/OB cho R:R tốt hơn.
- Không trust 1 FVG → phải có ChoCH/BOS context.
