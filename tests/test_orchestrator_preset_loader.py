from pathlib import Path

import pytest
import yaml

from vnstock_bot.orchestrator import list_presets, load_preset, validate_variables


@pytest.fixture
def swarm_dir(tmp_path) -> Path:
    base = tmp_path / "swarm"
    base.mkdir()
    return base


def _write(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_load_preset_success(swarm_dir):
    _write(swarm_dir / "p.yaml", {
        "name": "p",
        "title": "t",
        "nodes": [
            {"id": "a", "type": "function", "function": "f"},
        ],
    })
    spec = load_preset("p", swarm_dir=swarm_dir)
    assert spec.name == "p"
    assert spec.title == "t"
    assert len(spec.nodes) == 1


def test_load_preset_infers_name_from_filename(swarm_dir):
    _write(swarm_dir / "infer_me.yaml", {
        "nodes": [{"id": "a", "type": "function", "function": "f"}],
    })
    spec = load_preset("infer_me", swarm_dir=swarm_dir)
    assert spec.name == "infer_me"


def test_load_preset_not_found(swarm_dir):
    with pytest.raises(FileNotFoundError):
        load_preset("ghost", swarm_dir=swarm_dir)


def test_list_presets(swarm_dir):
    _write(swarm_dir / "a.yaml", {"nodes": [{"id": "x", "type": "function", "function": "f"}]})
    _write(swarm_dir / "b.yaml", {"nodes": [{"id": "x", "type": "function", "function": "f"}]})
    assert list_presets(swarm_dir=swarm_dir) == ["a", "b"]


def test_validate_variables_defaults_and_required(swarm_dir):
    _write(swarm_dir / "v.yaml", {
        "name": "v",
        "variables": [
            {"name": "ticker", "required": True},
            {"name": "days", "default": 60},
        ],
        "nodes": [{"id": "x", "type": "function", "function": "f"}],
    })
    spec = load_preset("v", swarm_dir=swarm_dir)
    # missing required
    with pytest.raises(ValueError, match="required"):
        validate_variables(spec, {})

    # default applied
    out = validate_variables(spec, {"ticker": "FPT"})
    assert out == {"ticker": "FPT", "days": 60}

    # user override beats default
    out2 = validate_variables(spec, {"ticker": "FPT", "days": 30})
    assert out2["days"] == 30


def test_real_shipped_presets_parse():
    """The two presets shipped in config/swarm/ must parse under Pydantic."""
    from vnstock_bot.orchestrator.preset_loader import DEFAULT_SWARM_DIR

    if not DEFAULT_SWARM_DIR.is_dir():
        pytest.skip("no swarm dir shipped")

    for name in list_presets():
        spec = load_preset(name)
        assert spec.name
        assert spec.nodes
