from vnstock_bot.memory.compression import Message, compress_context


def _mk_messages(n: int) -> list[Message]:
    return [
        Message(role="user" if i % 2 == 0 else "assistant",
                content=f"message number {i} about FPT trend")
        for i in range(n)
    ]


def test_compress_empty_returns_empty_string():
    assert compress_context([]) == ""


def test_compress_short_fits_in_budget():
    msgs = _mk_messages(3)
    out = compress_context(msgs, token_budget=1_000)
    assert "L1 — recent" in out
    assert "L2 — chunks" not in out   # nothing older than keep_recent
    assert "message number 0" in out


def test_compress_long_populates_l1_and_l2():
    msgs = _mk_messages(20)
    out = compress_context(msgs, token_budget=4_000, keep_recent=5, chunk_size=5)
    assert "L1 — recent" in out
    assert "L2 — chunks" in out
    # last message must be preserved verbatim in L1
    assert "message number 19" in out


def test_compress_truncates_when_over_budget():
    # Force very tight budget so truncation kicks in
    msgs = [Message(role="user", content="x" * 200) for _ in range(100)]
    out = compress_context(msgs, token_budget=100)
    assert len(out) // 4 <= 110   # within a small margin
