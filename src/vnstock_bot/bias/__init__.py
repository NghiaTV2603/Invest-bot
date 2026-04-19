"""V2 bias detection module.

Pure `list[TradeLike] → list[BiasResult]` — no DB reads, no persistence.
`bias.weekly_check` wraps detectors with DB queries + persistence.
"""

from __future__ import annotations

from vnstock_bot.bias.detectors import (
    anchoring,
    chase_momentum,
    detect_all,
    disposition_effect,
    hot_hand_sizing,
    overtrading,
    recency,
    skill_dogma,
)
from vnstock_bot.bias.types import (
    BiasName,
    BiasResult,
    BiasSeverity,
    DecisionLike,
    TradeLike,
)
from vnstock_bot.bias.weekly_check import persist_report, run_bot_bias_check

__all__ = [
    "BiasName",
    "BiasResult",
    "BiasSeverity",
    "TradeLike",
    "DecisionLike",
    "disposition_effect",
    "overtrading",
    "chase_momentum",
    "anchoring",
    "hot_hand_sizing",
    "skill_dogma",
    "recency",
    "detect_all",
    "run_bot_bias_check",
    "persist_report",
]
