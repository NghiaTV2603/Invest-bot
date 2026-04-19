---
name: stop-loss-rules
version: 1
status: active
category: risk
when_to_use: Xác định stop-loss cho vị thế mới hoặc update trailing stop
inputs: [entry_price, ohlc_60d, support_levels]
outputs: [stop_loss_price, stop_type]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Stop-loss **rõ ràng, khách quan, tự động**. Không để cảm xúc quyết định.

## Rules

### R1. Hard stop tuyệt đối
- Mọi vị thế: stop_loss ≥ -8% so với entry.
- Ví dụ entry 150,000 → stop tối đa = 138,000.
- Đây là **floor**, có thể đặt gần hơn (chặt hơn).

### R2. Structural stop (ưu tiên dùng nếu gần hơn -8%)
- Stop dưới **support gần nhất** (từ `technical-trend`) 1–2%.
- Ví dụ: entry 150, support gần nhất 145 → stop ~143 (-4.7%).
- Structural stop thường tốt hơn % stop vì tôn trọng cấu trúc giá.

### R3. Chọn giữa R1 và R2
```
stop_loss = max(entry × 0.92, support_gần_nhất × 0.98)
```
Nghĩa là: chọn stop **cao hơn** (gần giá hơn) giữa -8% và below-support.
Mục đích: minimize loss per trade.

### R4. Trailing stop (áp dụng khi vị thế +10%)
- Khi unrealized gain ≥ 10% → trailing stop = max(stop_hiện_tại, entry).
  Dịch stop về breakeven.
- Khi +20% → trailing stop = max(stop_hiện_tại, entry × 1.08). Locked-in 8%.
- Trailing stop chỉ dịch lên, không bao giờ dịch xuống.

### R5. Time stop
- Nếu sau **15 phiên giao dịch** vị thế vẫn range ±3% và không có catalyst mới
  → đề xuất SELL (capital inefficiency).

### R6. Biên độ check
- `stop_loss` phải trong biên độ giá sàn (HSX ±7% phiên hiện tại). Tuy nhiên,
  stop là giá **theo dõi**, không phải lệnh đặt — có thể nằm ngoài biên nếu
  tính cho nhiều phiên. Validator check: stop cách close hiện tại không quá
  20%.

### R7. Giá trị stop phải là int VND
- Làm tròn xuống (BUY context) / lên (SELL context) về bội số 50 hoặc 100 VND.
- Chuẩn bước giá HSX: 10 (<10k), 50 (10k-50k), 100 (≥50k).

## Evidence required khi apply
- Entry price (hoặc close hiện tại cho trailing)
- Support gần nhất từ technical-trend
- Stop được chọn + type ("pct_hard" | "structural" | "trailing" | "time")
- Max loss % = (entry - stop) / entry

## Không làm
- Không đặt stop "mềm" ("sẽ cân nhắc"). Stop phải là số cụ thể.
- Không mở rộng stop sau khi đã vào lệnh chỉ vì giá sắp chạm.
  Nếu muốn đổi stop, phải có thesis mới + ghi vào `risks` của decision mới.
