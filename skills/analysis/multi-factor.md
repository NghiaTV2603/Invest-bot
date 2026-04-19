---
name: multi-factor
version: 1
status: active
category: analysis
when_to_use: Combine nhiều factor đã pass factor-research để rank universe và select top-N
inputs: [factor_scores_per_ticker, ic_weights]
outputs: [composite_score, top_tickers, selected_weights]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Tổng hợp 3-5 factor đã pass IC test (từ `factor-research`) thành 1 composite
score để rank universe. Select top-N → equal weight hoặc inverse-vol weight.

## Prerequisites

- Mỗi factor phải có IC > 0.05, IR > 0.5 (từ `factor-research`).
- Ideal: chọn factor có correlation thấp với nhau (xem R3).

## Factor thường dùng cho VN market

| Factor | Công thức ngắn | IC expected (VN) |
|---|---|---|
| Momentum 20d | return_20d | 0.06-0.09 |
| Reversal 5d | -return_5d | 0.04-0.07 |
| Value (P/E low) | 1 / PE_TTM | 0.05-0.08 |
| Quality (ROE high) | ROE_TTM | 0.05-0.07 |
| Volatility (low) | -stdev(ret, 60) | 0.04-0.06 |
| Volume ratio | volume_5 / volume_60 | 0.03-0.05 |
| Foreign flow | foreign_net_20d | 0.05-0.08 |

## 3 cách combine (theo Vibe-Trading)

### Method 1: Equal-weight

```
composite_i = mean(zscore(factor_k_i))     for k in factors
```
- Đơn giản, robust. Default khi chưa có IC estimate ổn định.

### Method 2: IC-weighted

```
weight_k = IR_k / sum(|IR_k|)               # normalize
composite_i = sum(weight_k * zscore(factor_k_i))
```
- Factor có IR cao hơn = trọng số lớn hơn.
- Yêu cầu ≥ 500 phiên lịch sử để IR stable.

### Method 3: Orthogonalized (advanced)

```
# Schmidt orthogonalization:
# Loại bỏ collinearity giữa factor bằng regression lần lượt
f2_orth = f2 - beta_{2,1} * f1
f3_orth = f3 - beta_{3,1} * f1 - beta_{3,2} * f2_orth
```
- Giúp tránh đo cùng 1 thứ 2 lần (ví dụ momentum + reversal overlap).
- Dùng khi factor correlation > 0.5.

## Rules — select portfolio

### R1. Universe filter trước
- Loại mã ADV20 < 500k cp (liquidity).
- Loại mã trong downtrend mạnh (close < SMA200) — trừ khi factor set có reversal.
- Tối thiểu 30 mã còn lại trong universe.

### R2. Ranking
- Tính composite_score cho mỗi mã.
- Rank cross-section.
- Select **top 10-15** (tùy NAV và per-position cap).

### R3. Weighting (3 cách)
- **Equal weight**: 1/N.
- **Inverse volatility**: weight_i ∝ 1 / stdev(return_i, 60). Normalize.
- **Rank weight**: rank_i / sum(ranks). Top có weight cao hơn.

Default: **equal weight** + check `position-sizing` per-mã cap 20% NAV.

### R4. Rebalance frequency
- **Monthly** là chuẩn. Rebalance phiên đầu tháng ATO.
- Nếu signal rất noisy (IC mean chỉ 0.04) → rebalance weekly.

### R5. Sector constraint (QUAN TRỌNG VN)
- Áp dụng `correlation-check`: ≤ 2 mã/sector trong top-N.
- Nếu multi-factor rank 5 mã đầu cùng ngân hàng → chỉ pick 2, bỏ 3 mã còn lại,
  đôn mã khác lên.

### R6. Turnover control
- Nếu turnover rebalance > 50% holdings → scrutinize, có thể factor noisy
  hoặc overfitting. Tightening rules lại.

## Output required

```
universe_size: 47
selected: ["FPT", "HPG", "VNM", ...]
method: "ic_weighted"
composite_top1_score: 1.82   # z-units
composite_bottomN_score: 0.67
expected_ic: 0.07             # weighted avg
weights: {"FPT": 0.1, "HPG": 0.1, ...}
rebalance_turnover_pct: 23
```

## Không làm

- Không combine factor chưa test IC riêng biệt.
- Không add factor "vì logic nó hay" — phải có empirical evidence.
- Không over-optimize weight — equal weight thường robust hơn IC-weighted
  fit trong-sample.
