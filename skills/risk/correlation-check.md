---
name: correlation-check
version: 1
status: active
category: risk
when_to_use: Trước mỗi BUY/ADD, verify không dồn rủi ro vào 1 sector / 1 macro factor
inputs: [portfolio_holdings, new_ticker_sector, watchlist_sectors]
outputs: [concentration_ok, sector_count, correlated_risk_notes]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Tránh "all eggs in one basket". Một cú sốc ngành (ví dụ NHNN siết tín dụng →
ngân hàng + BĐS cùng sập) có thể xoá 30% NAV nếu portfolio concentrated.

## Rules

### R1. Sector concentration — hard gate
- **Tối đa 2 mã cùng sector**. Sector lấy từ `watchlist.yaml` (Banking, Tech,
  RealEstate, Consumer, Retail, Materials, Chemicals, Energy, Utilities,
  Airlines, Logistics, Pharma, Securities, IndustrialRE).
- Đang có 2 mã sector X → BUY mã thứ 3 cùng X: **REJECT** hoặc yêu cầu TRIM/SELL
  1 trong 2 mã cũ trước.

### R2. Macro cluster — soft gate
Các sector có tương quan cao theo macro factor, đếm chung khi áp R1 ≥ 4:

| Cluster | Sectors | Driver macro |
|---|---|---|
| **Lãi suất nhạy cảm** | Banking + Securities + RealEstate + IndustrialRE | Lãi suất điều hành, room tín dụng |
| **Commodity upstream** | Energy + Materials + Chemicals | Giá dầu / thép / phân bón |
| **Tiêu dùng nội địa** | Consumer + Retail + Airlines | GDP, thu nhập hộ gia đình |

- Nếu portfolio đã có ≥ 4 mã cùng 1 cluster → cẩn trọng, giảm conviction của
  mã mới cùng cluster xuống tối đa 3.
- Nếu ≥ 5 mã cùng cluster → REJECT BUY/ADD mới trong cluster.

### R3. Khối ngoại correlated
- Các mã "NN favorite" (FPT, HPG, MWG, VCB, …) thường cùng biến động theo
  dòng vốn ngoại. Nếu portfolio đã có ≥ 3 mã NN-heavy (giả định room NN đã
  kín hoặc sở hữu > 40%) → cẩn trọng thêm mã thứ 4 cùng đặc tính.

### R4. Beta cluster — avoid all-or-nothing
- Portfolio không nên chỉ toàn high-beta (SSI, VND, PVS, DGC) hoặc toàn
  defensive (VNM, DHG, POW, GAS).
- Target: mix 40-60% medium-beta + 20-30% defensive + ≤ 30% high-beta.

## Evidence required khi apply

- `portfolio_sectors`: list sector hiện có + count mỗi sector.
- `new_sector`: sector của ticker đang xét.
- `macro_cluster_counts`: đếm theo R2.
- `verdict`: PASS / REJECT / CAUTION + lý do cụ thể.

## Format output

```
portfolio_current: VCB(Banking), TCB(Banking), FPT(Tech), HPG(Materials)
new_ticker: BID (Banking)
R1: 2 Banking đã có, BUY BID → 3 → REJECT R1
action: reject OR propose TRIM một trong VCB/TCB trước khi BUY BID
```

## Không làm

- Không coi mã có correlation thấp là "diversified" — đếm sector trước tiên.
- Không dùng skill này để "tìm lý do từ chối" — mục đích là size rủi ro, nếu
  portfolio nhỏ (< 4 vị thế) thì R1 đủ, không cần R2/R3/R4.
- Không tính index (VNINDEX, VN30) vào concentration — index là reference,
  không phải holding.
