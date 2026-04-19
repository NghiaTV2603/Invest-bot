---
name: regime-filter
version: 1
status: active
category: risk
when_to_use: Giới hạn gross exposure + hạn chế BUY mới khi VN-Index ở risk-off regime
inputs: [vnindex_close, vnindex_sma200, breadth]
outputs: [regime_label, max_gross_pct, allowed_actions]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Hard gate portfolio-level: khi VN-Index ở regime tệ, **bỏ BUY mới**, giảm
gross exposure. Prevent fighting the tape.

## Regime logic

| Regime | VN-Index vs SMA200 | Breadth | Max gross | Allowed actions |
|---|---|---|---|---|
| **Risk-on strong** | > SMA200 + SMA200 up + > +5% YTD | > 60% mã trên SMA50 | 100% | All (BUY, ADD, TRIM, SELL, HOLD) |
| **Risk-on moderate** | > SMA200, SMA200 flat | 40-60% | 80% | BUY với conviction ≥ 4 |
| **Risk-off moderate** | < SMA200 nhưng > SMA50 | 30-40% | 60% | BUY chỉ với conviction ≥ 5 + catalyst ≥ 4 |
| **Risk-off strong** | < SMA200 + SMA200 down + < -10% 60d | < 30% | 40% | No BUY; ADD cho loại catalyst mạnh; TRIM/SELL OK |
| **Crash mode** | < -15% 20d hoặc VN-Index giảm 3 phiên liên tiếp ≥ 3%/phiên | — | 30% | No BUY/ADD; SELL theo `stop-loss-rules` |

## Rules

### R1. Compute regime daily
- Fetch VN-Index close + SMA50 + SMA200.
- Fetch breadth (% mã VN30 trên SMA50) từ market_snapshot.
- Apply bảng trên → regime label.

### R2. Hard gate trước `propose_trade`
```
if regime == "risk_off_strong" and action in {"BUY", "ADD"}:
    reject(reason="regime hard gate")
if gross_after_trade > max_gross_pct * nav:
    reject(reason="exceeds regime gross cap")
```

### R3. Transition handling
- Regime thay đổi trong 1 phiên có thể noisy. Require **2 phiên liên tiếp** ở
  regime mới trước khi apply rule mới.
- Ngoại lệ: **crash mode** kích ngay 1 phiên (tránh thiệt hại lan).

### R4. Interaction với drawdown-budget
- Gross cap cuối cùng = **min(regime_max, drawdown_budget_max)**.
- 2 filter tầng, filter nào chặt hơn thắng.

### R5. Re-entry after risk-off
- Regime từ risk-off → risk-on moderate cần **2 phiên** confirm.
- Sau đó, ease back: tuần đầu +20% gross, tuần 2 +20%, v.v. (don't go 0 → 100).

## Evidence required

- VN-Index close, SMA50, SMA200 hôm nay
- % change 20d, % change YTD của VN-Index
- Breadth (% mã VN30 trên SMA50)
- Regime label hiện tại + lần thay đổi gần nhất (ngày)
- Gross exposure hiện tại + cap theo regime

## Kết hợp action

- Regime filter là **first-line guard**. Chạy trước mọi skill khác.
- Decision tạo ra vi phạm regime → reject + log, không hỏi lại.

## Không làm

- Không override regime filter trừ khi human explicit via Telegram command
  (ghi lý do + decision_id vào strategy.md).
- Không dùng VN-Index alone — phải combine breadth để tránh "index hỗ trợ
  bởi vài mã lớn" ngộ nhận regime.
