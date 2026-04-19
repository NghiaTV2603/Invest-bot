"""Shadow backtest: classify real trades against extracted rules, compute
Delta-PnL attribution, return a ShadowBacktestResult.

This is NOT a full OHLC-based strategy replay — that would require
historical price access for every day (not just trade days). The W5
implementation is classification-based: "what would your PnL be if you'd
skipped the non-rule trades and cut losers at rule.max / held winners to
rule.min". Full OHLC replay is deferred to post-MVP.
"""

from __future__ import annotations

from vnstock_bot.shadow import delta_pnl
from vnstock_bot.shadow.types import Roundtrip, ShadowBacktestResult, ShadowRule


def run(
    shadow_id: str,
    roundtrips: list[Roundtrip],
    rules: list[ShadowRule],
) -> ShadowBacktestResult:
    result = delta_pnl.compute(roundtrips, rules)
    result.shadow_id = shadow_id
    return result
