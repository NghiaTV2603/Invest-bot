from __future__ import annotations

import html
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


# ---------------------------------------------------------------- markdown → Telegram HTML

# Telegram HTML supports: <b>, <i>, <u>, <s>, <code>, <pre>, <a href>.
# It does NOT support headings (#), tables, lists, horizontal rules.
# Claude output routinely contains all of these → we convert manually here.

_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|_{3,}|\*{3,})\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_LIST_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+")
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_BOLD_UND_RE = re.compile(r"__([^_\n]+)__")
_ITALIC_RE = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_FENCE_RE = re.compile(r"^```")


def _inline_format(text: str) -> str:
    """Handle inline `code`, **bold**, *italic* + HTML-escape the rest.
    Placeholder technique protects formatted tokens from html.escape."""
    tokens: list[str] = []

    def save(repl: str) -> str:
        tokens.append(repl)
        return f"\x00{len(tokens) - 1}\x00"

    # Order matters: code spans first (their content isn't re-interpreted),
    # then double-asterisk bold, then single-asterisk italic (which must not
    # match the leftover parts of **).
    text = _CODE_SPAN_RE.sub(
        lambda m: save(f"<code>{html.escape(m.group(1))}</code>"), text
    )
    text = _BOLD_RE.sub(
        lambda m: save(f"<b>{html.escape(m.group(1))}</b>"), text
    )
    text = _BOLD_UND_RE.sub(
        lambda m: save(f"<b>{html.escape(m.group(1))}</b>"), text
    )
    text = _ITALIC_RE.sub(
        lambda m: save(f"<i>{html.escape(m.group(1))}</i>"), text
    )

    # Escape everything that's left
    text = html.escape(text, quote=False)
    # Restore protected tokens
    text = _PLACEHOLDER_RE.sub(lambda m: tokens[int(m.group(1))], text)
    return text


def _render_table_as_pre(rows: list[str]) -> str:
    """Wrap a markdown pipe-table in <pre> so monospace preserves alignment.
    Strip the |---| separator row — it looks bad in monospace."""
    kept = [r for r in rows if not _TABLE_SEP_RE.match(r)]
    body = "\n".join(html.escape(r.strip()) for r in kept)
    return f"<pre>{body}</pre>"


def md_to_telegram_html(md: str) -> str:
    """Convert Claude-style markdown to Telegram-friendly HTML.

    Handles (common cases Claude produces):
      - # / ## / ### headings       → <b>heading</b>
      - **bold**, __bold__          → <b>…</b>
      - *italic*                    → <i>…</i>
      - `inline code`               → <code>…</code>
      - ```fenced code blocks```    → <pre>…</pre>
      - | pipe | tables |           → <pre>…</pre>  (monospace alignment)
      - --- horizontal rules        → ──────────── line
      - - list items                → • list items

    Any unmatched syntax is HTML-escaped. Safe to call on arbitrary
    Claude output — worst case user sees escaped text instead of broken
    HTML that Telegram rejects.
    """
    if not md:
        return ""

    lines = md.split("\n")
    out: list[str] = []
    i = 0
    table_buf: list[str] = []

    def flush_table() -> None:
        if table_buf:
            out.append(_render_table_as_pre(table_buf))
            table_buf.clear()

    while i < len(lines):
        line = lines[i]

        # Fenced code block ```...```
        if _FENCE_RE.match(line):
            flush_table()
            code_lines: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                code_lines.append(lines[i])
                i += 1
            out.append("<pre>" + html.escape("\n".join(code_lines)) + "</pre>")
            i += 1
            continue

        # Pipe-table
        if _TABLE_LINE_RE.match(line):
            table_buf.append(line)
            i += 1
            continue
        else:
            flush_table()

        # Horizontal rule
        if _HR_RE.match(line):
            out.append("────────────────")
            i += 1
            continue

        # Heading
        m = _HEADING_RE.match(line)
        if m:
            inner = _inline_format(m.group(2).strip())
            out.append(f"<b>{inner}</b>")
            i += 1
            continue

        # Bullet list: replace `- ` with `• `
        lm = _LIST_BULLET_RE.match(line)
        if lm:
            prefix = lm.group(1)
            rest = line[lm.end():]
            out.append(f"{prefix}• {_inline_format(rest)}")
            i += 1
            continue

        # Plain line with inline formatting
        out.append(_inline_format(line))
        i += 1

    flush_table()

    result = "\n".join(out)
    # Collapse 3+ blank lines to 2 for compactness
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result
