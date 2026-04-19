from vnstock_bot.memory.tokenizer import normalize, token_set, tokenize


def test_normalize_strips_vietnamese_diacritics():
    assert normalize("Mở rộng") == "mo rong"
    assert normalize("HOẠT động") == "hoat dong"
    assert normalize("Hưng Yên") == "hung yen"


def test_tokenize_keeps_alnum_and_underscores_min_len_3():
    tokens = tokenize("FPT tăng trưởng 12% YoY! AI_v2")
    # "12" is dropped (< 3), "%" is dropped, "yoy" kept
    assert "fpt" in tokens
    assert "tang" in tokens
    assert "truong" in tokens
    assert "yoy" in tokens
    assert "ai_v2" in tokens
    assert "12" not in tokens


def test_token_set_dedupes():
    s = token_set("FPT fpt FPT tăng TĂNG")
    assert s == {"fpt", "tang"}
