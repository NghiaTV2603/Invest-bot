from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

NodeStatus = Literal[
    "pending", "running", "success", "failed", "timeout", "skipped"
]
DagStatus = Literal[
    "pending", "running", "success", "failed", "timeout", "partial"
]
NodeType = Literal["agent", "function"]


class NodeSpec(BaseModel):
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: NodeType
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: int = 60

    # How outputs of upstream nodes are injected into this node's context
    # local_key -> upstream_node_id
    input_from: dict[str, str] = Field(default_factory=dict)

    # ---- AgentNode fields
    system_prompt: str | None = None
    prompt_template: str | None = None
    tools: list[str] = Field(default_factory=list)
    max_turns: int | None = None

    # ---- FunctionNode fields
    function: str | None = None                    # registry key
    function_kwargs: dict[str, Any] = Field(default_factory=dict)

    @field_validator("depends_on")
    @classmethod
    def _no_self_dep(cls, v: list[str], info):
        # We validate duplicates / cycles at DAG-build time; only sanity here.
        if len(set(v)) != len(v):
            raise ValueError("duplicate entry in depends_on")
        return v


class DagSpec(BaseModel):
    name: str = Field(..., pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = ""
    description: str = ""
    nodes: list[NodeSpec]
    variables: list[dict[str, Any]] = Field(default_factory=list)
    timeout_seconds: int = 180

    @field_validator("nodes")
    @classmethod
    def _unique_ids(cls, v: list[NodeSpec]):
        ids = [n.id for n in v]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate node id(s): {dupes}")
        id_set = set(ids)
        for n in v:
            unknown = [d for d in n.depends_on if d not in id_set]
            if unknown:
                raise ValueError(
                    f"node {n.id!r} depends on unknown node(s): {unknown}"
                )
            missing = [
                src for src in n.input_from.values() if src not in id_set
            ]
            if missing:
                raise ValueError(
                    f"node {n.id!r} input_from references unknown: {missing}"
                )
        return v


@dataclass
class NodeResult:
    node_id: str
    status: NodeStatus
    output: Any = None
    error: str | None = None
    started_at: str = ""
    ended_at: str = ""
    elapsed_ms: int = 0


@dataclass
class DagResult:
    trace_id: str
    preset: str
    status: DagStatus
    started_at: str
    ended_at: str
    elapsed_ms: int
    variables: dict[str, Any] = field(default_factory=dict)
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    final_output: Any = None
    error: str | None = None

    def node(self, node_id: str) -> NodeResult | None:
        return self.node_results.get(node_id)

    @property
    def succeeded(self) -> bool:
        return self.status == "success"
