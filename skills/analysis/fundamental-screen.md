---
name: fundamental-screen
version: 1
status: active
category: analysis
when_to_use: Đánh giá chất lượng doanh nghiệp trước khi BUY/ADD
inputs: [financial_ratios, eps_history, sector]
outputs: [quality_score, red_flags, green_flags]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Sàng lọc cơ bản: công ty có **chất lượng đủ** để mua dài hạn hay không.
Không thay thế phân tích sâu — chỉ là filter.

## Rules

### R1. Ngưỡng tối thiểu (hard gate)
Một mã chỉ được BUY nếu đạt TOÀN BỘ:
- **ROE TTM ≥ 12%** (ngoại trừ ngân hàng: ≥ 15%).
- **Nợ vay / Equity ≤ 2** (ngân hàng: bỏ qua rule này, thay bằng CAR ≥ 10%).
- **EPS growth YoY ≥ 0%** quý gần nhất (không giảm).
- **Không có ý kiến ngoại trừ** của kiểm toán 2 năm gần nhất.

### R2. Green flags (cộng điểm)
- ROE TTM ≥ 20%.
- Biên lãi gộp tăng liên tục 4 quý.
- Dòng tiền HĐKD > lợi nhuận kế toán (quality of earnings).
- Chia cổ tức tiền mặt đều đặn 3 năm.
- Room NN còn nhiều (< 40% đã sở hữu) → room cho dòng tiền ngoại.

### R3. Red flags (trừ điểm / reject)
- Nợ vay / Equity > 3 → REJECT (trừ BĐS, xem xét riêng).
- Phát hành tăng vốn > 30% vốn điều lệ trong 12 tháng → CẨN TRỌNG (dilution).
- Tồn kho / doanh thu tăng đột biến → CẨN TRỌNG.
- CEO/CFO đổi > 2 lần trong 2 năm → CẨN TRỌNG.
- Lỗ lũy kế → REJECT.

### R4. Định giá tương đối
- P/E TTM so với median ngành (dùng VN30 sector peers).
- **Undervalued**: P/E < 70% median ngành + ROE ≥ median.
- **Expensive**: P/E > 130% median ngành → cần catalyst mạnh để justify.

### R5. Quality score
```
score = min(5, max(1, 3 + green_flags - red_flags_severity))
```
- Score 1–2: REJECT.
- Score 3: HOLD/WATCH.
- Score 4–5: eligible để BUY.

## Evidence required
- ROE TTM + ngưỡng ngành
- Nợ vay / Equity
- EPS YoY 4 quý gần nhất
- P/E TTM + median ngành (nếu biết)
- Liệt kê green/red flags cụ thể

## Không làm
- Không kết luận dựa trên 1 chỉ số đơn lẻ.
- Không skip R1 (hard gate) vì "mã này có story".
