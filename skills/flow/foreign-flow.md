---
name: foreign-flow
version: 1
status: active
category: flow
when_to_use: Confirm bằng dòng tiền khối ngoại — mua ròng nhiều phiên liên tiếp = tín hiệu mạnh cho VN market
inputs: [foreign_net_buy_20d_per_ticker, net_flow_vnindex_20d]
outputs: [flow_signal, net_days, conviction_modifier]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Khối ngoại là mover lớn + có information edge ở VN. Dòng tiền FN kéo dài là
signal có trọng lượng. Skill này **không tự mua/bán** — chỉ điều chỉnh
conviction cho các skill khác.

## Nguồn data

- `market_snapshot.foreign_buy` và `foreign_sell` ở cấp VN-Index.
- Per-ticker: vnstock `foreign_room` / proprietary API.
- `foreign_net_X = foreign_buy_X - foreign_sell_X` đơn vị VND.

## Rules — per ticker

### R1. Persistent net buy (bullish)
- **≥ 5 phiên liên tiếp net buy** (mỗi phiên > 0) → **strong signal** (+2).
- 3-4 phiên liên tiếp → medium (+1).
- Tổng net_20d > 3% market cap ticker → **significant accumulation** (+2).

### R2. Persistent net sell (bearish)
- **≥ 5 phiên liên tiếp net sell** → **strong bearish** (-2).
- Tổng net_20d < -3% market cap → heavy distribution (-2).

### R3. Spike detection
- 1 phiên net buy ≥ 10% ADV20 + volume ≥ 2x MA20 → block trade / institutional
  accumulation, flag +1 (tin tức có thể chưa public).
- 1 phiên net sell cực lớn trên mã đã chạy mạnh → profit-taking, flag -1.

### R4. Room NN context
- Room NN đã hết (sở hữu nước ngoài = max) → net flow số 0 không âm. Xem qua
  sang proprietary-flow để confirm.
- Room NN còn nhiều (< 30% sở hữu) → dòng tiền ngoại có dư địa, signal mạnh hơn.

## Rules — thị trường tổng

### R5. Market-level flow
- VN-Index net buy 10 phiên liên tiếp → **regime tailwind**, boost conviction
  mọi BUY +1.
- Net sell 10 phiên → headwind, trừ conviction BUY −1.

## Conviction modifier

Skill này xuất ra **modifier** áp lên conviction của decision khác, không phải
quyết định độc lập:

| Flow signal | Conviction modifier |
|---|---|
| Strong persistent buy (≥ 5d) | +1 |
| Medium buy (3-4d) | 0 (confirm, không boost) |
| Neutral | 0 |
| Medium sell | -1 |
| Strong persistent sell | -2 |

- Modifier này cộng vào conviction cuối cùng, clip về [1, 5].

## Evidence required

- Foreign net 5 phiên gần nhất (VND, từng ngày)
- Foreign net 20d tổng (VND) + % market cap
- Room NN còn lại (%)
- VN-Index net flow 10-20 phiên (regime context)

## Không làm

- Không entry chỉ vì khối ngoại mua — phải combine với technical + fundamental.
- Không dùng flow 1 phiên đơn lẻ (quá nhiễu). Cần persistence hoặc size lớn.
- Không chống dòng tiền dài hạn — net sell 10 phiên thì dù bullish thesis
  cũng phải chờ hoặc lọc mã khác.
