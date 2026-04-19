---
name: position-sizing
version: 1
status: active
category: risk
when_to_use: Quyết định qty khi đề xuất BUY hoặc ADD
inputs: [nav, cash, conviction, stop_loss_pct, sector_exposure]
outputs: [qty, pct_nav, max_loss_vnd]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu
Size vị thế để **1 trade thua không vỡ NAV**. Max loss per trade ≤ 2% NAV.

## Rules

### R1. Conviction → % NAV
| Conviction | % NAV tối đa |
|---|---|
| 1 | 0 (HOLD) |
| 2 | 0 (HOLD) |
| 3 | 10% |
| 4 | 15% |
| 5 | 20% |

Hard cap: **20% NAV/mã** (chặn simulator).

### R2. Max loss rule (kiểm tra 2%)
```
max_loss_vnd = qty × (entry_price - stop_loss)
max_loss_vnd ≤ 2% × NAV
```
Nếu vi phạm, **giảm qty** cho đến khi pass, hoặc nới stop (nhưng không quá
rộng — xem `stop-loss-rules`).

### R3. Làm tròn xuống bội số 100
```
qty_final = (qty_target // 100) × 100
```
Nếu qty_final = 0 → không đủ vốn để vào, đề xuất HOLD hoặc giảm target ticker.

### R4. Sector concentration
- Không quá **2 mã cùng sector** trong portfolio.
- Nếu đang có 2 mã ngành X → BUY mã thứ 3 cùng ngành phải REJECT hoặc
  đề xuất TRIM mã cùng ngành trước.

### R5. Cash buffer
- Luôn giữ ≥ 10% NAV bằng cash.
- Nếu BUY mới làm cash < 10% → giảm qty.

### R6. ADD vs BUY sizing
- **ADD** chỉ khi vị thế cũ đang +10% trở lên.
- ADD qty ≤ 50% qty ban đầu của vị thế đó.
- Combined position vẫn ≤ 20% NAV sau ADD.

## Evidence required
- NAV hiện tại
- Cash hiện tại
- Conviction level
- Entry price dự kiến + stop_loss → max_loss_vnd
- Sector của ticker + số mã cùng sector đang nắm

## Formulas (để Claude tính ngay trong evidence)
```
qty_from_nav = (pct_nav × NAV) ÷ entry_price
qty_from_loss = (2% × NAV) ÷ (entry_price - stop_loss)
qty_target = min(qty_from_nav, qty_from_loss)
qty_final = floor(qty_target / 100) × 100
```
