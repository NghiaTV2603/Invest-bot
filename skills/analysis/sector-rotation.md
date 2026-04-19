---
name: sector-rotation
version: 1
status: active
category: analysis
when_to_use: Xác định sector đang dẫn dắt thị trường để ưu tiên mã cùng sector
inputs: [sector_returns_20d, sector_breadth, vnindex_return_20d]
outputs: [top_sectors, rotation_score, avoid_sectors]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Xếp hạng sector theo **relative strength** so với VN-Index — mua mã thuộc top
sector, tránh mã thuộc bottom sector. Port logic từ Vibe-Trading.

## Phân nhóm sector (VN market)

17 sector chính (có thể tra qua vnstock):
Banking, Real Estate, Construction, Steel, Securities, Retail, Oil & Gas,
Utilities (điện-nước), Food & Beverage, Tech (FPT, CMG), Logistics,
Aquaculture (thủy sản), Textiles (dệt may), Fertilizer, Insurance,
Healthcare, Industrials.

## Rules

### R1. Relative strength 20d

Với mỗi sector S:
```
RS_20d(S) = return_20d(S) - return_20d(VN-Index)
```

Sort descending → top 5, bottom 5.

### R2. Sector breadth
Breadth = % mã trong sector đóng cửa trên SMA20.
- **> 70%**: strong sector (healthy).
- **40-70%**: neutral.
- **< 40%**: weak sector (avoid).

### R3. Rotation score (per sector)
```
score = rs_rank_component + breadth_component + momentum_component
      ∈ [-3, +3]
```
| Component | +1 | 0 | -1 |
|---|---|---|---|
| RS rank | Top 5 | 6-12 | Bottom 5 |
| Breadth | >70% | 40-70% | <40% |
| Price vs sector SMA50 | > SMA50 | flat | < SMA50 |

- `score ≥ +2` → **leading sector**, ưu tiên pick từ đây.
- `score ≤ -2` → **lagging sector**, avoid BUY mới; holdings xem xét TRIM.
- `-1..+1` → neutral.

### R4. Rotation pattern
- Sector vừa leave bottom 5 (RS lần lượt -5%, -3%, +2% trong 20d) → **rotation
  vào**, watch close.
- Sector vừa leave top 5 → **rotation out**, cảnh báo.

### R5. Correlation với macro
- Interest rate xuống → banks, real estate, securities thường lead.
- Commodity cycle → steel (HPG, HSG), oil (GAS, PVS, BSR), fertilizer (DPM).
- Consumer confidence up → retail (MWG, PNJ), F&B (VNM, MSN).

## Evidence required

- Top 5 sector theo RS 20d (tên + số %)
- Bottom 5 sector
- Breadth của sector đang xem (nếu đang pick mã)
- Macro context từ `top-down-macro`

## Kết hợp với action

- Ứng cử viên BUY phải thuộc **top 10 sector** HOẶC có catalyst idiosyncratic
  mạnh (từ `catalyst-check`, strength ≥ 4).
- Holdings trong **bottom 5 sector kéo dài 3 tuần** → review, xem xét TRIM
  nếu không có catalyst mới.

## Không làm

- Không chọn mã chỉ vì sector hot — vẫn phải pass `fundamental-screen` + technical.
- Không bán tất cả ngay khi sector rơi bottom — rotation có thể ngắn.
