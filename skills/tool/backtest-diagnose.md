---
name: backtest-diagnose
version: 1
status: active
category: tool
when_to_use: Sau khi chạy backtest — diagnose có overfit / data leak / sample bias không trước khi tin
inputs: [backtest_metrics, trade_log, equity_curve]
outputs: [diagnosis, red_flags, recommended_next_steps]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Backtest đẹp ≠ strategy đẹp. Phân tích 15 metrics + sanity checks để phát hiện
overfit, survivorship bias, lookahead, và các lỗi khác.

## 15 metrics check (port từ Vibe-Trading)

| # | Metric | Healthy | Suspicious |
|---|---|---|---|
| 1 | `final_value` | > initial | < initial → strategy thua |
| 2 | `total_return` | > VN-Index cùng kỳ | negative / underperform |
| 3 | `annual_return` | > 12% | > 50% = overfit suspect |
| 4 | `max_drawdown` | > -25% | > -40% = không tradeable |
| 5 | `sharpe` | 1.0-2.0 | **> 2.5 = overfit red flag** |
| 6 | `calmar` | > 1.0 | > 3 unusual |
| 7 | `sortino` | > 1.5 | — |
| 8 | `win_rate` | > 50% | > 70% + sharpe high = suspect |
| 9 | `profit_loss_ratio` | > 1.5 | — |
| 10 | `profit_factor` | > 1.2 | < 1.0 strategy lỗ |
| 11 | `max_consec_loss` | < 5 | ≥ 8 volatile |
| 12 | `avg_holding_days` | 5-20 (swing) | < 2 = intraday/noisy |
| 13 | `trade_count` | > 30 | < 30 không meaningful |
| 14 | `excess_return` (vs VN-Index) | > 0 | ≤ 0 worse than index |
| 15 | `information_ratio` | > 0.5 | < 0 = strategy hại hơn index |

## Red flags — must investigate

### RF1. Sharpe > 2.5 với < 100 trades
- Quá đẹp = overfit. Thử out-of-sample hoặc walk-forward.
- Test: split data 70/30, re-run chỉ 70% đầu. Nếu Sharpe rơi > 50% → overfit.

### RF2. Equity curve quá mượt
- Equity curve không có drawdown > 5% trong 2+ năm = overfit hoặc lookahead.
- Visual: plot equity curve, dùng rolling 20-day max-drawdown.

### RF3. Lookahead bias check
- Verify: strategy tại bar t chỉ dùng data ≤ t-1 (hoặc t close nếu EOD).
- Test: shift toàn bộ signal về 1 bar → Sharpe rớt hẳn? Có thể bias.

### RF4. Survivorship bias
- Universe backtest chỉ chứa VN30 hiện tại? Mã bị delist/hủy niêm yết trong
  period bị bỏ sót → kết quả đẹp giả.
- Sửa: include "point-in-time" universe (tại mỗi ngày, VN30 là gì).

### RF5. Fee/slippage dưới mức
- VN: mua 0.15%, bán 0.25% (có thuế TNCN). Slippage ≈ 0.1% cho mã Tier 1.
- Total round-trip ≈ 0.5%. Strategy trade 100 lần/năm = 50% return eat up by fee.
- Nếu backtest không tính fee → **redo** với fee 0.5% round-trip.

### RF6. Trade count < 30
- Không đủ significant. Bootstrap CI sẽ rất rộng.
- Mở rộng backtest window hoặc relax entry rules.

### RF7. Chỉ 1 mã / 1 sector
- Kết quả không generalize. Backtest tối thiểu 10 ticker cross-section.

### RF8. Max drawdown xảy ra ở cuối period
- Có thể data kết thúc đúng lúc crash → unlucky.
- Verify: tra lại thời điểm draw down chính, so với macro event.

## Suggested validations (từ Vibe-Trading)

Chạy 3 method này trước khi tin:
1. **Monte Carlo permutation** (n=1000): shuffle trade order → tính Sharpe
   distribution. Nếu Sharpe strategy nằm trong top 5% → p < 0.05.
2. **Bootstrap** (n=1000): resample daily returns. Tính Sharpe CI 95%. Nếu CI
   không chứa 0 → significant.
3. **Walk-forward** (n=5 windows): chia period 5 cửa sổ, train 70%/test 30%
   mỗi window. Nếu ≥ 4/5 window có Sharpe > 0.5 → robust.

Strategy phải pass **≥ 2/3** methods mới eligible "active" trong lifecycle.

## Output required

```
overall_verdict: "pass" | "suspect" | "fail"
red_flags: ["RF1: sharpe 2.8 with 42 trades"]
sanity_checks_passed: 4 / 8
validation_results:
  monte_carlo_p: 0.03
  bootstrap_sharpe_ci_95: [0.72, 1.4]
  walk_forward_pass_count: 4
next_steps:
  - "rerun with fee 0.5% round-trip"
  - "expand universe to 20 ticker"
```

## Không làm

- Không auto-promote strategy với Sharpe > 2 mà chưa OOS test.
- Không so sánh với SPY/QQQ cho VN strategy — benchmark phải là VN-Index.
- Không bỏ qua trade_count — hiệp một đẹp không nghĩa là chiến thắng dài hạn.
