---
name: liquidity-check
version: 1
status: active
category: flow
when_to_use: Hard gate — loại mã thanh khoản thấp khỏi universe BUY
inputs: [volume_20d, current_price]
outputs: [adv20_shares, adv20_vnd, liquidity_bucket, max_size_pct_nav]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Slippage + exit risk là killer cho retail VN khi mã nhỏ. Skill này là filter
đầu tiên — mã không pass, **không research tiếp**.

## Công thức

```
ADV20_shares = mean(volume trong 20 phiên)
ADV20_vnd    = mean(volume * close trong 20 phiên)
```

## Buckets

| Bucket | ADV20 shares | ADV20 VND | Max size /trade | Max % NAV |
|---|---|---|---|---|
| **Tier 1 (blue chip)** | ≥ 2M cp | ≥ 200 tỷ | 20% NAV OK | 20% |
| **Tier 2 (mid liquidity)** | 500k-2M | 50-200 tỷ | 15% NAV | 15% |
| **Tier 3 (low liquidity)** | 100k-500k | 10-50 tỷ | 8% NAV | 8% |
| **Tier 4 (illiquid)** | < 100k | < 10 tỷ | **BLOCK** | 0 |

## Rules

### R1. Hard block Tier 4
- **ADV20 < 100k cp hoặc < 10 tỷ VND** → **reject BUY**, không research tiếp.
- Lý do: 1 lệnh trong gói 5-10% NAV có thể gây slippage 3-5%.

### R2. Size cap per tier
- Qty đề xuất **không vượt 5% ADV20 shares** trong 1 trade.
  *(Quy tắc: 1 trade chỉ ăn ≤ 5% liquidity ngày thường; nếu cần vào hết theo
  gói, chia nhỏ thành 3-5 phiên.)*

### R3. Intraday spread proxy
- Nếu có data tick: spread % = (ask - bid) / mid. Loại mã spread > 2%.
- Không có data tick: xấp xỉ bằng (high - low) / close trung bình 20 phiên.
  Mã có daily range trung bình < 1.5% và volume thấp = spread khả năng lớn.

### R4. Volume trend
- ADV20 giảm 50% so với ADV60 → mã đang "chết", kể cả đang tier 2 cũng phải
  downgrade 1 bậc.
- ADV20 tăng 50% so với ADV60 + giá đi lên → volume breakout (positive signal),
  upgrade nếu phù hợp.

### R5. Sell-side check
- Khi SELL: liquidity càng quan trọng. Nếu position size > 3×ADV20 → cần bán
  trải 5-10 phiên, không bán 1 phiên (trừ stop-loss cứng).

## Output required

```
ticker: "XXX"
adv20_shares: 850000
adv20_vnd: 85000000000   # 85 tỷ
bucket: "tier_2"
max_size_pct_nav: 15
max_qty_this_trade: 42500  # 5% ADV20
block_buy: false
spread_warning: false
```

## Kết hợp action

- **Mọi BUY/ADD** phải pass liquidity-check trước khi đi qua skill khác.
- Position sizing (`position-sizing`) nhận max_size_pct_nav từ đây làm hard cap.
- Trong DAG daily research: liquidity-check là **node đầu** trong technical panel.

## Không làm

- Không "thử tí cho vui" với Tier 4 — 1 lần kẹt là khó thoát.
- Không bỏ qua spread check ở UPCOM — thường có spread 5-10%.
- Không rely vào ADV dài hạn (60+ ngày) vì có thể outdated — dùng ADV20.
