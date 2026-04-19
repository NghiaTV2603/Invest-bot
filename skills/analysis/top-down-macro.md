---
name: top-down-macro
version: 1
status: active
category: analysis
when_to_use: Đánh giá bối cảnh thị trường chung trước khi quyết định mở/đóng vị thế
inputs: [vnindex_ohlc_60d, foreign_flow_20d, vn30_sectors]
outputs: [market_regime, caution_level]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Xác định thị trường đang ở regime nào — **uptrend / sideway / downtrend** —
để biết nên aggressive hay phòng thủ.

## Rules

### R1. Regime theo VN-Index
- **UPTREND**: VN-Index close > SMA50 > SMA200, và SMA50 dốc lên ≥ 10 phiên.
- **DOWNTREND**: VN-Index close < SMA50 < SMA200, và SMA50 dốc xuống ≥ 10 phiên.
- **SIDEWAY**: còn lại.

### R2. Khối ngoại
- **Positive**: mua ròng ≥ 3/5 phiên gần nhất hoặc tổng 20 phiên > 0.
- **Negative**: bán ròng ≥ 4/5 phiên gần nhất.
- Trọng số: positive + uptrend → aggressive; negative + sideway → cẩn trọng.

### R3. Thanh khoản thị trường
- GTGD trung bình 20 phiên.
- Nếu hôm nay < 60% trung bình → **thanh khoản kém**, bỏ BUY mới.
- Nếu > 150% trung bình + tăng giá → **xác nhận momentum**.

### R4. Biên độ VN-Index trong 20 phiên
- Nếu VN-Index đã tăng > 8% trong 20 phiên → **cẩn trọng mua mới** (risk of pullback).
- Nếu đã giảm > 8% → ưu tiên tìm đáy, không chạy theo bán.

## Evidence required khi apply skill này
- VN-Index close hôm nay + SMA50 + SMA200
- Khối ngoại mua/bán ròng 5 phiên + 20 phiên gần nhất (tỷ VND)
- GTGD hôm nay + MA20 GTGD
- % thay đổi VN-Index 20 phiên

## Output format
```
market_regime: "UPTREND" | "SIDEWAY" | "DOWNTREND"
caution_level: 1 (aggressive) → 5 (defensive)
notes: string (1-2 câu giải thích)
```

## Kết hợp với hành động
- DOWNTREND + caution ≥ 4 → chỉ cho phép SELL/TRIM/HOLD, chặn BUY mới.
- UPTREND + caution ≤ 2 → cho phép BUY với conviction ≥ 3.
- SIDEWAY → chỉ BUY khi conviction ≥ 4 và có catalyst rõ.
