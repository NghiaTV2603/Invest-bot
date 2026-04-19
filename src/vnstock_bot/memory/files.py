"""L2/L4 markdown memory files with YAML frontmatter.

Layer layout under `settings.absolute_memory_dir`:

    memory/
      user_prefs/<key>.md     -- L2: risk tolerance, preferred sectors, etc.
      project/<key>.md        -- L4: per-project context (backtest config, ...)
      reference/<key>.md      -- L4: holiday calendar, KQKD dates, thresholds
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import yaml

from vnstock_bot.config import get_settings
from vnstock_bot.memory.types import MemoryFile, MemoryLayer

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)$",
    re.DOTALL,
)
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
_VALID_LAYERS: tuple[str, ...] = get_args(MemoryLayer)


def _layer_dir(layer: MemoryLayer) -> Path:
    if layer not in _VALID_LAYERS:
        raise ValueError(f"unknown memory layer: {layer}")
    path = get_settings().absolute_memory_dir / layer
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate_key(key: str) -> str:
    key = key.strip().lower()
    if not _KEY_RE.match(key):
        raise ValueError(
            f"invalid memory key {key!r} — use [a-z0-9_-], 1-64 chars"
        )
    return key


def _parse(path: Path, layer: MemoryLayer) -> MemoryFile:
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if m:
        frontmatter = yaml.safe_load(m.group("fm")) or {}
        body = m.group("body").lstrip("\n")
    else:
        frontmatter = {}
        body = text
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return MemoryFile(
        path=path,
        layer=layer,
        name=path.stem,
        frontmatter=frontmatter,
        body=body,
    )


def read_memory_file(layer: MemoryLayer, key: str) -> MemoryFile | None:
    path = _layer_dir(layer) / f"{_validate_key(key)}.md"
    if not path.is_file():
        return None
    return _parse(path, layer)


def write_memory_file(
    layer: MemoryLayer,
    key: str,
    body: str,
    frontmatter: dict[str, Any] | None = None,
) -> MemoryFile:
    path = _layer_dir(layer) / f"{_validate_key(key)}.md"
    fm = dict(frontmatter or {})
    fm.setdefault("title", key.replace("_", " ").replace("-", " "))
    fm_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{fm_yaml}\n---\n\n{body.strip()}\n", encoding="utf-8")
    return _parse(path, layer)


def delete_memory_file(layer: MemoryLayer, key: str) -> bool:
    path = _layer_dir(layer) / f"{_validate_key(key)}.md"
    if path.is_file():
        path.unlink()
        return True
    return False


def list_memory_files(layer: MemoryLayer | None = None) -> list[MemoryFile]:
    layers = (layer,) if layer else _VALID_LAYERS
    out: list[MemoryFile] = []
    for layer_name in layers:
        for path in sorted(_layer_dir(layer_name).glob("*.md")):
            out.append(_parse(path, layer_name))  # type: ignore[arg-type]
    return out
