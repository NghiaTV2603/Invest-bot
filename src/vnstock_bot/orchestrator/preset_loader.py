"""YAML preset loader.

Each preset lives under `config/swarm/<name>.yaml`. Validation is delegated
to Pydantic via `DagSpec(**yaml_dict)` — field typos or bad cross-refs fail
at load time with a clear Pydantic error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from vnstock_bot.config import PROJECT_ROOT
from vnstock_bot.orchestrator.types import DagSpec

DEFAULT_SWARM_DIR = PROJECT_ROOT / "config" / "swarm"


def preset_path(name: str, swarm_dir: Path | None = None) -> Path:
    base = swarm_dir or DEFAULT_SWARM_DIR
    return base / f"{name}.yaml"


def load_preset(name: str, swarm_dir: Path | None = None) -> DagSpec:
    path = preset_path(name, swarm_dir)
    if not path.is_file():
        raise FileNotFoundError(
            f"preset {name!r} not found at {path} "
            f"(avail: {list_presets(swarm_dir)})"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"preset {path}: expected YAML mapping, got {type(raw).__name__}")
    # YAML `name` is optional — default to file stem.
    raw.setdefault("name", path.stem)
    return DagSpec(**raw)


def list_presets(swarm_dir: Path | None = None) -> list[str]:
    base = swarm_dir or DEFAULT_SWARM_DIR
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.glob("*.yaml"))


def validate_variables(spec: DagSpec, variables: dict[str, Any]) -> dict[str, Any]:
    """Enforce `variables: [{name, required, default}]` constraints from the
    preset. Returns the materialized variables (with defaults applied)."""
    out: dict[str, Any] = dict(variables)
    for var_decl in spec.variables:
        name = var_decl.get("name")
        if not isinstance(name, str):
            raise ValueError(f"preset {spec.name!r}: variable missing 'name'")
        if name not in out:
            if "default" in var_decl:
                out[name] = var_decl["default"]
            elif var_decl.get("required", False):
                raise ValueError(
                    f"preset {spec.name!r}: required variable {name!r} not supplied"
                )
    return out
