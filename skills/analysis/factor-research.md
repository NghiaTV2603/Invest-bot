---
name: factor-research
version: 1
status: active
category: analysis
when_to_use: Kiểm chứng 1 factor (momentum/value/quality) có predictive power trước khi đưa vào strategy
inputs: [factor_series_cross_section, forward_return_series]
outputs: [ic_mean, ic_std, ir, ic_positive_ratio, quantile_equity]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Test xem 1 factor (PE, momentum, ROE, volatility…) có thực sự dự báo
forward return hay không. Port công thức từ Vibe-Trading.

## Thresholds (từ Vibe-Trading thực nghiệm)

| Metric | Công thức | Pass threshold | Ý nghĩa |
|---|---|---|---|
| **IC mean** | mean(corr(factor_t, fwd_ret_{t+1})) | > 0.05 | Factor có edge |
| **IR** | IC_mean / IC_std | > 0.5 | Edge ổn định |
| **IC positive ratio** | % period IC > 0 | > 55% | Hướng ổn định |
| **Quantile monotonic** | top quantile return > bottom | Required | Signal tăng dần |

## Rules — testing workflow

### R1. Data preparation
- Cross-section ≥ 30 ticker cùng thời điểm (VN30 + mở rộng lên 50 mã).
- Factor value tính EOD, forward return tính 5/10/20 phiên sau.
- Loại outlier: Winsorize factor tại 1% và 99%.
- Normalize cross-section: z-score trong từng ngày.

### R2. IC (Information Coefficient)
```
IC_t = corr(factor_rank_t, forward_return_rank_{t+N})     # Spearman rank
IC_mean = mean(IC_t) over backtest window
IC_std  = stdev(IC_t)
IR      = IC_mean / IC_std * sqrt(252)                    # annualized
```
- **IC_mean > 0.05** = factor có edge (thực nghiệm VN/EM phù hợp).
- **IC_std / IC_mean < 2** = không quá noisy.

### R3. Quantile backtest
- Chia universe thành 5 quantile theo factor value mỗi rebal day.
- Long top quantile, short bottom (paper — VN không short cá nhân được) hoặc
  chỉ long top.
- Tính equity curve từng quantile.
- **Monotonic check**: Q5 > Q4 > Q3 > Q2 > Q1 trong return cumulative.
  Không monotonic = factor yếu/noisy.

### R4. Decay test
- Tính IC với forward_return 1d, 5d, 10d, 20d.
- Factor tốt: IC peak ở 5-10d, decay dần.
- Nếu IC peak ở 1d rồi rơi mạnh = có thể noise / reversal factor.

### R5. Stability by regime
- Split backtest window làm 2-3 period (uptrend vs downtrend).
- Factor nào work toàn regime mới robust. Factor chỉ work trong 1 regime =
  conditional factor (vẫn OK nhưng phải combine filter).

## Output required

```
factor_name: "momentum_20d"
ic_mean: 0.078
ic_std: 0.12
ir: 0.65
ic_positive_ratio: 0.62
quantile_monotonic: true
top_quantile_annual_return: 18.2%
bottom_quantile_annual_return: 4.1%
regime_stability: "works in uptrend & sideway, underperforms in downtrend"
verdict: "PASS — add to multi-factor with weight ~15%"
```

## Kết hợp action

- **Factor pass** → đưa vào `multi-factor` combine với trọng số theo IR.
- **Factor fail** → không dùng làm signal chính, có thể dùng làm filter phụ.

## Không làm

- Không test factor trên < 30 mã — không đủ cross-sectional power.
- Không lookback < 1 năm (250 phiên) — không đủ sample IC.
- Không chỉ nhìn IC mean — phải xem IR và quantile monotonic cùng lúc.
