"""Vietnamese-aware tokenizer for scoring outside FTS5.

SQLite FTS5 uses `unicode61 remove_diacritics 2` which already handles
diacritics + case folding at index time. This module mirrors that behavior in
Python so metadata-weight scoring (title vs body) and recall-similarity can
match what FTS5 indexes. Keep the two in sync — if you change FTS5
`tokenize=` in schema.sql, update `normalize()` here.
"""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")

# NFD cannot decompose these — "đ"/"Đ" are precomposed Latin letters with a
# stroke, not base+combining. FTS5's unicode61 folds them to "d", so we do too.
_LATIN_FOLDS = str.maketrans({"đ": "d", "Đ": "d", "ð": "d", "Ð": "d"})


def normalize(text: str) -> str:
    # NFD splits "ở" → "o" + combining-horn + combining-hook; category 'Mn' is
    # the combining marks. Dropping them gives ASCII-lowered text that matches
    # FTS5's unicode61 remove_diacritics output. The pre-lowercase translate
    # covers "đ"/"Đ" which NFD leaves intact.
    pre = text.translate(_LATIN_FOLDS).lower()
    decomposed = unicodedata.normalize("NFD", pre)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalize(text))


def token_set(text: str) -> set[str]:
    return set(tokenize(text))
