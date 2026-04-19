"""Shadow Account HTML report — 8 sections per PLAN_V2 §5.5.

No external template engine: uses plain f-strings to avoid adding a dep.
Output is a single self-contained HTML file (CSS inlined) the user can open
in any browser.

Sections:
  1. Executive summary (PnL gap headline)
  2. Trading profile (hold days, frequency, top symbols/sectors)
  3. Shadow equity curve vs real (inline SVG)
  4. Rules detail (human_text, support, coverage, win-rate)
  5. ★ Delta-PnL attribution (5 components) — MAIN INSIGHT
  6. Counterfactual Top-5
  7. Per-sector comparison
  8. Actionable recommendations

PDF output (WeasyPrint) is NOT implemented in W5 — requires system libs
(cairo/pango). The HTML renders cleanly in print-preview for a casual PDF.
"""

from __future__ import annotations

import html
from pathlib import Path

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.shadow.types import (
    ShadowBacktestResult,
    ShadowRule,
    TradingProfile,
)

_CSS = """
body { font-family: -apple-system, 'Helvetica Neue', Arial, sans-serif;
       max-width: 980px; margin: 24px auto; padding: 0 20px; color:#1f2328; }
h1 { border-bottom: 3px solid #0969da; padding-bottom: 8px; }
h2 { color: #0969da; margin-top: 32px; border-bottom: 1px solid #d0d7de;
     padding-bottom: 4px; }
h3 { margin-top: 20px; }
.delta-positive { color: #1a7f37; font-weight: 700; }
.delta-negative { color: #cf222e; font-weight: 700; }
.headline { font-size: 20px; background: #fafbfc; padding: 16px 20px;
            border-left: 4px solid #0969da; margin: 16px 0; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { padding: 6px 10px; border-bottom: 1px solid #d0d7de; text-align: left; }
th { background: #f6f8fa; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.component { margin: 8px 0; padding: 10px 16px; border-radius: 6px;
             background: #fafbfc; }
.component.high { border-left: 4px solid #cf222e; }
.component.medium { border-left: 4px solid #d29922; }
.component.low { border-left: 4px solid #8c959f; }
.rule { background: #f6f8fa; padding: 12px 16px; margin: 8px 0;
        border-radius: 6px; }
.rule strong { font-size: 15px; }
svg { background: #fff; border: 1px solid #d0d7de; border-radius: 6px; }
small { color: #656d76; }
"""


def _fmt_vnd(value: int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):,} VND"


def _delta_class(value: int) -> str:
    return "delta-positive" if value > 0 else "delta-negative"


def _section_summary(
    profile: TradingProfile, result: ShadowBacktestResult
) -> str:
    delta_cls = _delta_class(result.delta_pnl)
    verdict = (
        "Nếu theo rule của chính bạn, bạn đã có thêm"
        if result.delta_pnl > 0
        else "Theo rule của chính bạn tốt hơn chỉ"
    )
    return f"""<section id="s1">
<h2>1. Tóm tắt</h2>
<div class="headline">
  <div>Real PnL: <strong>{_fmt_vnd(result.real_pnl)}</strong></div>
  <div>Shadow PnL: <strong>{_fmt_vnd(result.shadow_pnl)}</strong></div>
  <div>Delta: <span class="{delta_cls}">{_fmt_vnd(result.delta_pnl)}</span></div>
  <div style="margin-top:8px;"><small>{verdict} <span class="{delta_cls}">
  {_fmt_vnd(abs(result.delta_pnl))}</span> trong {profile.total_roundtrips}
  roundtrip từ {profile.start_date} đến {profile.end_date}.</small></div>
</div>
</section>"""


def _section_profile(profile: TradingProfile) -> str:
    top_tickers = ", ".join(f"{t} ({n})" for t, n in profile.top_tickers_by_trades[:5]) or "—"
    top_sectors = ", ".join(f"{s} ({n})" for s, n in profile.top_sectors[:5]) or "—"
    return f"""<section id="s2">
<h2>2. Trading profile</h2>
<table>
  <tr><th>Tổng trades</th><td class="num">{profile.total_trades:,}</td>
      <th>Roundtrips</th><td class="num">{profile.total_roundtrips:,}</td></tr>
  <tr><th>Win rate</th><td class="num">{profile.win_rate:.1%}</td>
      <th>Avg hold (days)</th><td class="num">{profile.avg_hold_days:.1f}</td></tr>
  <tr><th>Total PnL</th><td class="num">{_fmt_vnd(profile.total_pnl)}</td>
      <th>Avg win / Avg loss</th>
      <td class="num">{_fmt_vnd(profile.avg_win_pnl)} / {_fmt_vnd(profile.avg_loss_pnl)}</td></tr>
</table>
<p><strong>Top tickers:</strong> {html.escape(top_tickers)}</p>
<p><strong>Top sectors:</strong> {html.escape(top_sectors)}</p>
</section>"""


def _svg_equity_curve(
    real: list[tuple[str, int]],
    shadow: list[tuple[str, int]],
    width: int = 900,
    height: int = 240,
) -> str:
    if not real and not shadow:
        return "<p><em>(No data)</em></p>"
    pad = 30
    all_pnl = [p for _, p in real + shadow] or [0]
    min_y = min(all_pnl + [0])
    max_y = max(all_pnl + [0])
    # Avoid zero range
    if min_y == max_y:
        max_y = min_y + 1
    n = max(len(real), len(shadow), 1)

    def _to_xy(idx: int, v: int) -> tuple[float, float]:
        x = pad + (width - 2 * pad) * idx / max(n - 1, 1)
        y = height - pad - (height - 2 * pad) * (v - min_y) / (max_y - min_y)
        return x, y

    def _path(series: list[tuple[str, int]]) -> str:
        if not series:
            return ""
        pts = [_to_xy(i, v) for i, (_, v) in enumerate(series)]
        return " ".join(
            ("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}"
            for i, (x, y) in enumerate(pts)
        )

    zero_y = _to_xy(0, 0)[1]
    return f"""<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <line x1="{pad}" y1="{zero_y:.1f}" x2="{width - pad}" y2="{zero_y:.1f}"
        stroke="#d0d7de" stroke-dasharray="3,3"/>
  <path d="{_path(real)}" fill="none" stroke="#cf222e" stroke-width="2"/>
  <path d="{_path(shadow)}" fill="none" stroke="#1a7f37" stroke-width="2"/>
  <text x="{width - pad - 160}" y="{pad}" fill="#cf222e" font-size="12">● Real PnL</text>
  <text x="{width - pad - 70}" y="{pad}" fill="#1a7f37" font-size="12">● Shadow</text>
</svg>"""


def _section_equity(result: ShadowBacktestResult) -> str:
    svg = _svg_equity_curve(result.real_equity, result.shadow_equity)
    return f"""<section id="s3">
<h2>3. Equity curve — Real vs Shadow</h2>
<p><small>Cumulative PnL theo thời gian sell. Đường đỏ = thực tế bạn đã
làm; đường xanh = nếu chỉ giữ trade match rule + điều chỉnh sớm/muộn theo
rule range.</small></p>
{svg}
</section>"""


def _section_rules(rules: list[ShadowRule]) -> str:
    if not rules:
        return """<section id="s4">
<h2>4. Rules đã rút</h2><p><em>Không đủ dữ liệu thắng để extract rule.</em></p>
</section>"""
    items = []
    for r in rules:
        items.append(f"""<div class="rule">
  <strong>{html.escape(r.human_text)}</strong>
  <div><small>{r.rule_id} · support {r.support_count} trade ·
  coverage {r.coverage_rate:.0%} · cluster win-rate {r.win_rate:.0%} ·
  hold {r.holding_min}-{r.holding_max} ngày</small></div>
</div>""")
    return f"""<section id="s4">
<h2>4. Rules rút từ trade thắng</h2>
{''.join(items)}
</section>"""


def _component_severity(value: int, total: int) -> str:
    if total == 0:
        return "low"
    share = abs(value) / max(abs(total), 1)
    if share > 0.3:
        return "high"
    if share > 0.1:
        return "medium"
    return "low"


def _section_delta(result: ShadowBacktestResult) -> str:
    comps = result.components
    total = (abs(comps.noise_trades_pnl) + abs(comps.early_exit_pnl)
             + abs(comps.late_exit_pnl) + abs(comps.overtrading_pnl)
             + abs(comps.missed_signals_pnl))
    rows = [
        ("Noise trades (không match rule nào)", comps.noise_trades_pnl,
         "Trade cảm xúc — không khớp rule nào. Nếu bỏ những trade này,"
         " Shadow PnL không bao gồm chúng."),
        ("Early exit cost (thoát sớm winner)", comps.early_exit_pnl,
         "Winner hold ngắn hơn rule.min — bỏ lỡ phần uplift."),
        ("Late exit cost (giữ loser quá lâu)", comps.late_exit_pnl,
         "Loser hold dài hơn rule.max — mức lỗ đáng lẽ cắt được."),
        ("Overtrading cost", comps.overtrading_pnl,
         "Trade thứ 3+ trong cùng ngày — dấu hiệu revenge-trading."),
        ("Missed signals (residual)", comps.missed_signals_pnl,
         "Phần dư không attribute được."),
    ]
    html_rows = []
    for label, value, explain in rows:
        sev = _component_severity(value, total)
        cls = _delta_class(value)
        html_rows.append(f"""<div class="component {sev}">
  <div><strong>{html.escape(label)}</strong>:
       <span class="{cls}">{_fmt_vnd(value)}</span></div>
  <small>{html.escape(explain)}</small>
</div>""")
    return f"""<section id="s5">
<h2>5. ★ Delta-PnL attribution</h2>
<p>Đây là section quan trọng nhất. Tổng 5 component ≈ gap giữa Real PnL
và Shadow PnL.</p>
{''.join(html_rows)}
</section>"""


def _section_counterfactuals(result: ShadowBacktestResult) -> str:
    if not result.counterfactuals:
        return """<section id="s6">
<h2>6. Top-5 counterfactual trades</h2>
<p><em>(Không có counterfactual đáng kể)</em></p></section>"""
    rows = []
    for cf in result.counterfactuals[:5]:
        ticker = html.escape(str(cf.get("ticker", "")))
        typ = str(cf.get("type", ""))
        advice = html.escape(str(cf.get("advice", "")))
        pnl = int(cf.get("pnl", 0) or 0)
        extra_vnd = int(cf.get("missed_vnd", 0) or cf.get("saved_vnd", 0) or 0)
        rows.append(f"""<tr>
  <td>{ticker}</td>
  <td>{typ}</td>
  <td class="num">{_fmt_vnd(pnl)}</td>
  <td class="num">{_fmt_vnd(extra_vnd) if extra_vnd else '—'}</td>
  <td>{advice}</td>
</tr>""")
    return f"""<section id="s6">
<h2>6. Top-5 counterfactual trades</h2>
<table>
  <tr><th>Ticker</th><th>Type</th><th>Real PnL</th><th>Δ VND</th><th>Advice</th></tr>
  {''.join(rows)}
</table>
</section>"""


def _section_per_sector(result: ShadowBacktestResult) -> str:
    if not result.per_sector:
        return """<section id="s7">
<h2>7. Per-sector comparison</h2>
<p><em>(Không có sector data)</em></p></section>"""
    rows = []
    for sector, stats in sorted(
        result.per_sector.items(),
        key=lambda kv: -kv[1]["real_pnl"],
    ):
        rows.append(f"""<tr>
  <td>{html.escape(sector)}</td>
  <td class="num">{stats['count']}</td>
  <td class="num">{_fmt_vnd(stats['real_pnl'])}</td>
  <td class="num">{_fmt_vnd(stats['rule_conforming_pnl'])}</td>
</tr>""")
    return f"""<section id="s7">
<h2>7. Per-sector comparison</h2>
<table>
  <tr><th>Sector</th><th>Trades</th><th>Real PnL</th>
      <th>Rule-conforming PnL</th></tr>
  {''.join(rows)}
</table>
</section>"""


def _section_actions(
    profile: TradingProfile, result: ShadowBacktestResult
) -> str:
    if profile.total_roundtrips == 0:
        return "<section id='s8'><h2>8. Khuyến nghị</h2></section>"
    delta_per_trade = result.delta_pnl // max(profile.total_roundtrips, 1)
    cls = _delta_class(result.delta_pnl)
    advice_items = []
    if result.components.noise_trades_pnl < 0:
        advice_items.append(
            "Bỏ trade cảm xúc — component <em>noise trades</em> "
            f"đang âm {_fmt_vnd(abs(result.components.noise_trades_pnl))}."
        )
    if result.components.late_exit_pnl > 0:
        advice_items.append(
            "Cắt loser đúng deadline (rule.holding_max) — có thể save "
            f"{_fmt_vnd(result.components.late_exit_pnl)}."
        )
    if result.components.early_exit_pnl > 0:
        advice_items.append(
            "Giữ winner đủ rule.holding_min — bỏ lỡ "
            f"{_fmt_vnd(result.components.early_exit_pnl)} uplift."
        )
    if result.components.overtrading_pnl < 0:
        advice_items.append(
            "Giới hạn ≤ 2 trade/ngày — <em>overtrading</em> đang kéo "
            f"{_fmt_vnd(result.components.overtrading_pnl)}."
        )
    if not advice_items:
        advice_items.append(
            "Tiếp tục duy trì discipline — không có bias đáng kể."
        )
    items = "".join(f"<li>{a}</li>" for a in advice_items)
    return f"""<section id="s8">
<h2>8. Khuyến nghị</h2>
<p class="headline">
  Trung bình mỗi roundtrip, shadow <span class="{cls}">
  {_fmt_vnd(delta_per_trade)}</span> so với thực tế.
</p>
<ul>{items}</ul>
<p><small>Đây là gợi ý từ dữ liệu lịch sử của chính bạn —
không phải lời khuyên đầu tư. Pattern quá khứ có thể không lặp lại.</small></p>
</section>"""


def render_html(
    profile: TradingProfile,
    rules: list[ShadowRule],
    result: ShadowBacktestResult,
) -> str:
    generated = now_vn().strftime("%Y-%m-%d %H:%M")
    body = "\n".join([
        _section_summary(profile, result),
        _section_profile(profile),
        _section_equity(result),
        _section_rules(rules),
        _section_delta(result),
        _section_counterfactuals(result),
        _section_per_sector(result),
        _section_actions(profile, result),
    ])
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<title>Shadow Account Report — {html.escape(result.shadow_id or 'unknown')}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Shadow Account Report</h1>
<p><small>Shadow ID: {html.escape(result.shadow_id or 'unknown')} ·
Generated {generated}</small></p>
{body}
</body>
</html>"""


def write_html(
    profile: TradingProfile,
    rules: list[ShadowRule],
    result: ShadowBacktestResult,
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        render_html(profile, rules, result),
        encoding="utf-8",
    )
    return out_path
