---
name: valuation-model
version: 1
status: active
category: analysis
when_to_use: Cân nhắc giá hiện tại đắt hay rẻ trước BUY — so PE/PB/EV-EBITDA với median ngành VN
inputs: [financial_ratios, sector_peers]
outputs: [valuation_score, upside_pct, fair_value_estimate]
parent_skill: null
uses: 0
trades_with_signal: 0
win_rate_20d: null
win_rate_ci_95: null
walk_forward_stable: null
shadow_vs_parent: null
---

## Mục tiêu

Trả lời: giá hiện tại có hợp lý không, upside/downside đến fair value bao
nhiêu. Phải so với **peer cùng ngành VN** (không so với peer US/TQ vì
discount market khác).

## Ngưỡng theo ngành VN (thực nghiệm 2020-2025)

| Ngành | P/E median | P/B median | EV/EBITDA median | ROE expected |
|---|---|---|---|---|
| Banking | 7-10 | 1.2-2.0 | — | 15-22% |
| Real Estate | 10-15 | 1.0-1.8 | 12-18 | 8-15% |
| Steel | 7-11 | 1.0-1.5 | 6-9 | 10-18% |
| Securities | 10-14 | 1.5-2.5 | — | 12-20% |
| Retail | 15-22 | 2.5-4.0 | 10-14 | 15-25% |
| F&B (FMCG) | 15-20 | 3.0-5.0 | 9-13 | 18-28% |
| Technology | 18-25 | 3.5-5.5 | 12-18 | 20-30% |
| Utilities (điện/nước) | 10-13 | 1.2-1.8 | 6-9 | 10-15% |
| Oil & Gas | 8-12 | 1.5-2.5 | 5-8 | 12-20% |
| Fertilizer | 6-10 | 1.0-1.8 | 4-7 | 10-20% |

*Ngưỡng trên dùng làm benchmark — mã cá biệt có thể lệch 30% có lý do.*

## Rules

### R1. PE screening
- **PE TTM < 0.7 × median ngành** + ROE ≥ median ngành → **undervalued** (+2).
- **PE ∈ [0.7, 1.1] × median** → **fair** (0).
- **PE > 1.3 × median** → **expensive** (-1). Cần catalyst mạnh mới justify.
- **PE > 2 × median** → **bubble zone** (-2). Trừ mã growth thật (EPS growth > 30% 3 năm).

### R2. PB + ROE (chất lượng book value)
- Lưu ý: **PB cao với ROE cao = justified**; PB cao với ROE thấp = đắt.
- Rule: P/B ≤ (ROE / 12%) × PB_median_ngành. Nếu PB cao hơn thì expensive
  relative to quality.

### R3. EV/EBITDA (bỏ qua cho ngân hàng)
- So với median ngành.
- EV/EBITDA > 1.3 × median → expensive dù PE có thể trông OK (do capital structure).

### R4. PEG (growth-adjusted)
- PEG = PE / EPS_growth_3y_CAGR.
- **PEG < 1.0** → cheap relative to growth.
- **PEG 1-1.5** → fair.
- **PEG > 2** → đắt.

### R5. Composite valuation score

```
score = pe_component + pb_roe_component + ev_ebitda_component + peg_component
      ∈ [-4, +4]
```
- `≥ +3` → **undervalued strong** — BUY eligible với conviction cao.
- `+1..+2` → mildly undervalued.
- `-1..+1` → fair.
- `-2..-3` → overvalued, cần catalyst.
- `≤ -4` → bubble, avoid.

### R6. Fair value estimate (đơn giản)
```
fair_value = current_price * (median_PE_ngành / current_PE)
upside_pct = (fair_value - current_price) / current_price
```
- Sanity check: upside/downside > ±50% → có lẽ input sai.

## Evidence required

- PE TTM + median ngành
- P/B + ROE TTM + median ngành
- EV/EBITDA nếu relevant + median
- EPS growth 3-year CAGR
- Danh 3-5 peer cụ thể (ticker + PE + PB của họ)

## Kết hợp action

- **Score ≥ +3**: BUY có discount, combine với `catalyst-check`.
- **Score ≤ -3**: **KHÔNG BUY** dù technical đẹp. Holdings cân nhắc TRIM.

## Không làm

- Không so PE với peer ngành khác (ngân hàng ≠ công nghệ).
- Không dùng PE âm (công ty lỗ) — chuyển sang EV/Sales hoặc PB.
- Không skip PEG khi mã growth — PE cao có thể cheap nếu growth rất mạnh.
