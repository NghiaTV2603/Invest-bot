from __future__ import annotations

import re

# Telegram MarkdownV2 special chars
_MD_V2 = r"_*[]()~`>#+-=|{}.!"


def escape_md_v2(text: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", text)


def fmt_vnd(n: int) -> str:
    return f"{n:,}₫".replace(",", ".")


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%"


def truncate(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 20] + "\n…(truncated)"
