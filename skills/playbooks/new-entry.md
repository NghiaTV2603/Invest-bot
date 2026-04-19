---
name: new-entry
version: 1
status: active
category: playbook
trigger: Muốn BUY một ticker chưa có trong holdings
required_skills: [top-down-macro, technical-trend, fundamental-screen, position-sizing, stop-loss-rules]
parent_skill: null
uses: 0
---

## Checklist — PHẢI PASS 7/7 mới được đề xuất BUY

1. **[ ] Macro check** (`top-down-macro`)
   - `market_regime` ≠ DOWNTREND (DOWNTREND → REJECT).
   - `caution_level` ≤ 3. Nếu = 4 chỉ cho conviction 5.

2. **[ ] Trend check** (`technical-trend`)
   - Mã đang UPTREND hoặc có breakout up xác nhận volume.
   - Nếu SIDEWAY: bắt buộc có breakout + volume ≥ 1.5 × MA20.

3. **[ ] Fundamental gate** (`fundamental-screen`)
   - PASS R1 hard gate (ROE, D/E, EPS growth, không ngoại trừ kiểm toán).
   - Quality score ≥ 4.

4. **[ ] Catalyst**
   - Có ≥ 1 catalyst cụ thể trong 30 ngày qua HOẶC kỳ vọng 90 ngày tới.
   - Ví dụ: KQKD tốt, hợp đồng lớn, M&A, chia cổ tức cao, policy thuận lợi.
   - Nếu không có catalyst → chờ, đừng BUY chỉ vì "đẹp kỹ thuật".

5. **[ ] Stop-loss & risk/reward**
   - Stop-loss xác định theo `stop-loss-rules`.
   - Target price (≥ 1 resistance xa hoặc +15% entry, lấy min).
   - R:R = (target - entry) / (entry - stop) ≥ **2:1**. Dưới 2:1 → REJECT.

6. **[ ] Position sizing** (`position-sizing`)
   - qty pass hết: R1 (conviction cap), R2 (max_loss 2% NAV), R3 (bội 100),
     R4 (sector concentration ≤ 2), R5 (cash ≥ 10% sau BUY).

7. **[ ] Biên độ & thanh khoản**
   - Entry price trong biên độ phiên hiện tại.
   - Thanh khoản MA20 ≥ 500,000 cp/phiên. Dưới ngưỡng: REJECT.

## Nếu 7/7 PASS → output decision

```json
{
  "action": "BUY",
  "skills_used": ["top-down-macro","technical-trend","fundamental-screen","position-sizing","stop-loss-rules"],
  "playbook_used": "new-entry",
  "evidence": [
    "macro: regime=UPTREND, caution=2",
    "trend: close 148.5, SMA20=144, SMA50=138, breakout @148 với vol 1.8× MA20",
    "fundamental: ROE 26%, D/E 0.4, EPS Q1 +18% YoY, score 5",
    "catalyst: KQKD Q1/2026 công bố 15/04, EPS beat consensus 12%",
    "risk: stop 137 (structural, -7.7%), target 168 (R = 2.5:1)",
    "sizing: NAV 100tr, conviction 4 → 15% = 15tr → 100cp @148.5 = 14.85tr, max_loss = 1.15tr = 1.15% NAV",
    "thanh khoản: MA20 vol = 3.2M cp/phiên ✓"
  ],
  "invalidation": "close < 143,000 sau 2 phiên liên tiếp OR vol_5d < 0.5× MA20 vol"
}
```

## Fail 1 checklist → output

```json
{ "action": "HOLD", "thesis": "new-entry checklist failed at step X", ... }
```

Hoặc nếu muốn watch: `action: HOLD` với note cụ thể điều kiện sẽ re-evaluate.
