---
name: breakout
version: 1
status: active
category: strategy
when_to_use: Trade setup phá đỉnh / phá kháng cự — cần volume xác nhận
inputs: [ohlc_60d]
outputs: [breakout_detected, breakout_level, confirmation_strength]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Phát hiện & xác nhận breakout **có chất lượng** — phá kháng cự với volume
đủ mạnh, không phải breakout fake.

## Thông số

- Lookback: **20 phiên** (breakout đỉnh 20 ngày) — có thể 55 cho swing dài.
- Volume confirm: **≥ 2.0 × MA20 volume** ngày breakout.
- Retest allowance: 3 phiên sau breakout cho phép pullback về level.

## Rules

### R1. Detect breakout (bullish)
- Close hôm nay > `max(high trong N-1 phiên trước)` (tức đỉnh 20 phiên không
  tính hôm nay).
- Và close > max(close N phiên) — filter out pin-bar breakout thất bại.

### R2. Volume confirm (quan trọng nhất)
- **Volume breakout ≥ 2.0 × MA20** → **strong** (score +2).
- Volume 1.5-2.0 × MA20 → **medium** (+1).
- Volume < 1.5 × MA20 → **weak** (0) — **KHÔNG entry** breakout này.
- Volume < MA20 → **fake breakout warning** (-1).

### R3. Context filter
- Breakout **chỉ đếm** nếu `top-down-macro` regime != DOWNTREND.
- Breakout gần resistance cấu trúc nhiều năm → độ mạnh × 1.5.
- Breakout từ vùng tích lũy chặt ≥ 20 phiên (range < 7%) → độ mạnh × 1.3.

### R4. Entry timing
- **Aggressive**: entry ngay ngày breakout (cuối phiên nếu volume > 2×MA20).
- **Conservative**: đợi retest — pullback về level cũ (nay là support) trong
  1-3 phiên + bật lên. R:R tốt hơn nhưng có thể miss.

### R5. Stop & target
- Stop: 5% dưới breakout level HOẶC dưới swing low gần nhất — cái nào gần hơn.
- Target 1: +1.5 × (entry − stop). Target 2: resistance tiếp theo.

### R6. Fake breakout detection (exit)
- Close quay về dưới breakout level trong 3 phiên đầu → **exit full, không chờ stop**.
- Volume spike nhưng close về gần mid-range (body pct < 30%) → signal yếu.

## Compound score

```
strength = volume_ratio_score + context_score + timing_score
         ∈ [-2, +4]
```
- `≥ +3` → high conviction entry (4-5).
- `+1..+2` → medium (conviction 3), size nhỏ hơn.
- `≤ 0` → don't trade, rà lại.

## Evidence required

- Close hôm nay + max(high 20 phiên trước đó)
- Volume hôm nay + MA20 volume + tỷ số
- Range của vùng tích lũy trước breakout
- Top-down-macro regime
- Stop price + target price cụ thể (VND int)

## Không làm

- Không entry breakout ở mã đã tăng > 20% trong 10 phiên (đỉnh extended).
- Không chase breakout đã +5% ngay trong phiên nếu chưa đóng cửa.
- Không bỏ volume rule — "breakout không volume" là cách thua tiền kinh điển.
