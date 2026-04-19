import pytest
from pydantic import ValidationError

from vnstock_bot.orchestrator import DagSpec, NodeSpec


def _spec(nodes: list[dict]) -> DagSpec:
    return DagSpec(name="t", nodes=[NodeSpec(**n) for n in nodes])


def test_duplicate_node_ids_rejected():
    with pytest.raises(ValidationError) as ei:
        _spec([{"id": "a", "type": "function", "function": "f"},
               {"id": "a", "type": "function", "function": "f"}])
    assert "duplicate" in str(ei.value).lower()


def test_unknown_dependency_rejected():
    with pytest.raises(ValidationError) as ei:
        _spec([{"id": "a", "type": "function", "function": "f",
                "depends_on": ["nope"]}])
    assert "unknown" in str(ei.value).lower()


def test_input_from_unknown_node_rejected():
    with pytest.raises(ValidationError) as ei:
        _spec([
            {"id": "a", "type": "function", "function": "f"},
            {"id": "b", "type": "function", "function": "f",
             "depends_on": ["a"], "input_from": {"x": "ghost"}},
        ])
    assert "unknown" in str(ei.value).lower()


def test_valid_spec_builds():
    spec = _spec([
        {"id": "a", "type": "function", "function": "fa"},
        {"id": "b", "type": "function", "function": "fb",
         "depends_on": ["a"], "input_from": {"up": "a"}},
    ])
    assert len(spec.nodes) == 2
    assert spec.nodes[1].input_from == {"up": "a"}
