from vnstock_bot.telegram.format import md_to_telegram_html


def test_empty_returns_empty():
    assert md_to_telegram_html("") == ""


def test_heading_becomes_bold():
    out = md_to_telegram_html("### 🌐 Thị trường")
    assert out == "<b>🌐 Thị trường</b>"


def test_bold_inline():
    out = md_to_telegram_html("**VN-Index:** 1.812,44 điểm")
    assert "<b>VN-Index:</b>" in out
    assert "1.812,44 điểm" in out


def test_italic_inline():
    out = md_to_telegram_html("This is *emphasized* text")
    assert "<i>emphasized</i>" in out


def test_code_span():
    out = md_to_telegram_html("call `get_price` tool")
    assert "<code>get_price</code>" in out


def test_bullet_list_converts_to_middot():
    out = md_to_telegram_html("- first\n- second")
    assert "• first" in out
    assert "• second" in out


def test_horizontal_rule():
    out = md_to_telegram_html("above\n---\nbelow")
    assert "────" in out


def test_pipe_table_wrapped_in_pre():
    md = "| Ticker | Giá |\n|---|---|\n| FPT | 77.000 |\n| VNM | 65.000 |"
    out = md_to_telegram_html(md)
    assert "<pre>" in out and "</pre>" in out
    assert "FPT" in out and "77.000" in out
    # Separator row dropped
    assert "---" not in out


def test_fenced_code_block():
    md = "```\nprint('hi')\n```"
    out = md_to_telegram_html(md)
    assert "<pre>" in out
    assert "print(&#x27;hi&#x27;)" in out or "print('hi')" in out


def test_html_chars_in_plain_text_escaped():
    out = md_to_telegram_html("a < b and c > d & e")
    assert "&lt;" in out and "&gt;" in out and "&amp;" in out


def test_full_message_like_telegram_example():
    md = """Có rồi! Dữ liệu hôm nay **20/04/2026**:

---

### 🌐 Thị trường
- **VN-Index:** 1.812,44 điểm | KL: 90,3 triệu cp

**Top tăng:**
| Ticker | Giá | +/- |
|--------|-----|-----|
| KBC | 35.650 | +1,71% |
| FPT | 77.000 | +1,32% |
"""
    out = md_to_telegram_html(md)
    # No raw ### should survive
    assert "###" not in out
    # No raw ** around VN-Index
    assert "**VN-Index" not in out
    # Heading became <b>
    assert "<b>🌐 Thị trường</b>" in out
    # Table is inside <pre>
    assert "<pre>" in out and "KBC" in out
    # --- horizontal line → box-drawing
    assert "────" in out
    # List bullet
    assert "• " in out


def test_malformed_does_not_throw():
    # Unbalanced asterisks — must degrade gracefully, not raise
    md = "**unclosed bold and *dangling italic"
    out = md_to_telegram_html(md)
    # Asterisks either removed/escaped — no raw <b> left unclosed
    assert out.count("<b>") == out.count("</b>")
    assert out.count("<i>") == out.count("</i>")


def test_nested_bold_in_heading():
    out = md_to_telegram_html("### Thông tin **quan trọng**")
    # Heading becomes outer bold, inner bold merges — at minimum no **  left
    assert "**" not in out
    assert "<b>" in out
