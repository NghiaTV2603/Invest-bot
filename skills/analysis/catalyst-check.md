---
name: catalyst-check
version: 1
status: active
category: analysis
when_to_use: Xác định ticker có catalyst trong 30 ngày qua HOẶC kỳ vọng 90 ngày tới (bắt buộc cho playbook new-entry)
inputs: [ticker, recent_price_action, fundamentals]
outputs: [catalyst_type, catalyst_strength, expected_timeline]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Trả lời dứt khoát: **ticker này có catalyst không?** Không có catalyst → đừng BUY,
dù đẹp kỹ thuật tới đâu (đi ngang có thể kéo dài 6 tháng).

## Định nghĩa catalyst

Event khách quan, có timeline, đủ trọng lượng để đẩy giá ≥ 10% trong 30–90 phiên.
Không phải "tôi nghĩ mã này sẽ lên".

## Các loại catalyst (sắp theo độ tin cậy giảm dần)

### C1. Earnings & báo cáo tài chính
- **KQKD đã công bố, EPS beat consensus ≥ 10%** → đây là catalyst mạnh nhất,
  thường kéo giá 10–25% trong 30 phiên.
- **Dự đoán KQKD quý tiếp theo tích cực** (từ BCTC trước + guidance): **tầm
  trung**, cần confirm bằng price action.
- Lịch công bố: quý 1 công bố cuối tháng 4, quý 2 cuối tháng 7, quý 3 cuối
  tháng 10, năm cuối tháng 3 năm sau. ĐHCĐ thường tháng 4–6.

### C2. Corporate action
- **Chia cổ tức tiền mặt ≥ 8% market cap**: catalyst tạm, thường lên trước
  ngày GDKHQ 1–2 tuần rồi giảm nhẹ sau ngày đó.
- **Chia cổ tức cổ phiếu / phát hành cho cổ đông**: mơ hồ — chỉ mua khi tỷ lệ
  ưu đãi rõ (vd giá ưu đãi < 70% thị giá).
- **M&A, thâu tóm công bố chính thức** (không tin đồn): **mạnh**, thường lên
  5–15% ngày công bố.
- **Niêm yết trên sàn khác, chuyển sàn HNX→HSX**: trung bình.
- **Phát hành cổ phiếu riêng lẻ giá ≥ thị giá**: tích cực (tin tưởng từ đối tác).
- **Phát hành cổ phiếu giá thấp hơn thị giá > 20%**: **âm** — dilution, thường
  giảm giá. NOT a buying catalyst.

### C3. Macro / policy
- **NHNN giảm lãi suất điều hành**: catalyst cho ngân hàng, BĐS, chứng khoán.
- **NHNN nới room tín dụng**: catalyst ngân hàng.
- **Luật/nghị định mới thuận lợi** (BĐS, chứng khoán, đầu tư công): trung bình,
  cần verify ngành thực sự hưởng lợi.
- **Nâng hạng thị trường (frontier → emerging, FTSE / MSCI)**: catalyst rất
  mạnh cho toàn thị trường + đặc biệt các mã room NN hết.

### C4. Ngành / sector
- **Giá commodity đầu vào/đầu ra thay đổi ≥ 15%** (thép, dầu, LNG, urea):
  catalyst cho ngành tương ứng (HPG-NKG, PVS-GAS-BSR, DPM-DCM).
- **Đơn hàng xuất khẩu tăng** (dệt may, điện tử, thuỷ sản): verify qua số
  liệu hải quan.

### C5. Technical / flow (NOT a fundamental catalyst, score thấp)
- Khối ngoại mua ròng liên tục ≥ 5 phiên: supporting signal, không đủ là
  catalyst độc lập.
- Break kháng cự dài hạn với volume: technical, không phải catalyst theo
  định nghĩa skill này.

## Catalyst strength (1–5)

| Strength | Ví dụ |
|---|---|
| 5 | M&A ăn chắc + giá đề nghị > 20% thị giá |
| 4 | KQKD quý beat ≥ 15%, đã công bố |
| 3 | Cổ tức tiền mặt ≥ 8%, ngày GDKHQ trong 30 ngày |
| 2 | Chính sách ngành tích cực, chưa rõ tác động cụ thể |
| 1 | Tin đồn, chưa verify |

## Evidence required (bắt buộc)

Khi apply skill này phải output đủ:
- `catalyst_type`: C1/C2/C3/C4
- `catalyst_specific`: ví dụ "KQKD Q1/2026 EPS +18% YoY công bố 15/04"
- `source_date`: ngày công bố / dự kiến công bố
- `expected_timeline`: số ngày đến khi catalyst thể hiện vào giá
- `strength`: 1–5

## Rule quyết định

- **Không có catalyst ≥ 3**: reject BUY trong playbook new-entry.
- **Catalyst strength 1–2**: chỉ HOLD/WATCH, không BUY.
- **Catalyst strength 3–5**: eligible, combine với các skill khác.

## Không làm
- Không coi "giá đã chạy + volume tốt" là catalyst — đó là **result** của
  catalyst, không phải catalyst.
- Không coi "kỳ vọng ngành tăng trưởng" là catalyst nếu không có event cụ thể.
- Không pyramid catalyst cũ — một catalyst chỉ dùng 1 lần cho 1 entry.
