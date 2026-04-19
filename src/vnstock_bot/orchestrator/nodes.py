"""Node runners: AgentRunner (Claude SDK) + FunctionRunner (pure Python).

Runners are instantiated fresh per DAG run. They receive a shared context
containing `variables` (DAG inputs) + `upstream` (outputs of resolved
dependencies via NodeSpec.input_from).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from vnstock_bot.orchestrator.types import NodeSpec

# Registered functions available to FunctionRunner via YAML preset. Lookup is
# done at DAG build time — unknown names fail fast, not at runtime.
FunctionImpl = Callable[..., Awaitable[Any]]
_FN_REGISTRY: dict[str, FunctionImpl] = {}


def register_function(name: str) -> Callable[[FunctionImpl], FunctionImpl]:
    def deco(fn: FunctionImpl) -> FunctionImpl:
        if name in _FN_REGISTRY:
            raise ValueError(f"function {name!r} already registered")
        _FN_REGISTRY[name] = fn
        return fn
    return deco


def get_function(name: str) -> FunctionImpl:
    if name not in _FN_REGISTRY:
        raise KeyError(
            f"function {name!r} not registered — "
            f"known: {sorted(_FN_REGISTRY)}"
        )
    return _FN_REGISTRY[name]


def _clear_registry_for_tests() -> None:
    _FN_REGISTRY.clear()


@dataclass
class NodeContext:
    node_id: str
    variables: dict[str, Any] = field(default_factory=dict)
    upstream: dict[str, Any] = field(default_factory=dict)   # input_from resolved
    trace_id: str = ""


class NodeRunner(Protocol):
    async def run(self, ctx: NodeContext) -> Any: ...


def _render_template(template: str | None, ctx: NodeContext) -> str:
    if not template:
        return ""
    values: dict[str, Any] = {**ctx.variables, **ctx.upstream}
    try:
        return template.format_map(_SafeDict(values))
    except Exception:  # noqa: BLE001
        return template


class _SafeDict(dict):
    """dict that leaves unknown placeholders intact instead of KeyError."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


@dataclass
class FunctionRunner:
    spec: NodeSpec

    async def run(self, ctx: NodeContext) -> Any:
        if not self.spec.function:
            raise ValueError(f"node {self.spec.id}: function name is empty")
        fn = get_function(self.spec.function)
        kwargs = dict(self.spec.function_kwargs)
        return await fn(ctx=ctx, **kwargs)


@dataclass
class AgentRunner:
    spec: NodeSpec
    # Injected to keep Claude SDK out of tests. Production wires this to
    # research.agent.run_agent via `make_default_agent_runner()`.
    agent_fn: Callable[..., Awaitable[Any]] | None = None

    async def run(self, ctx: NodeContext) -> Any:
        if self.agent_fn is None:
            raise RuntimeError(
                f"node {self.spec.id}: AgentRunner.agent_fn is not wired"
            )
        user_prompt = _render_template(self.spec.prompt_template, ctx)
        system_prompt = _render_template(self.spec.system_prompt, ctx)
        result = await self.agent_fn(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            tool_names=list(self.spec.tools),
            max_turns=self.spec.max_turns,
        )
        # research.agent.run_agent returns an AgentResult dataclass;
        # serialize to plain dict so it's easy to JSON-persist in traces.
        return {
            "text": getattr(result, "text", str(result)),
            "turns": getattr(result, "turns", 0),
            "tokens_used": getattr(result, "tokens_used", 0),
        }


def make_runner(spec: NodeSpec, agent_fn: Callable | None = None) -> NodeRunner:
    if spec.type == "function":
        return FunctionRunner(spec=spec)
    if spec.type == "agent":
        return AgentRunner(spec=spec, agent_fn=agent_fn)
    raise ValueError(f"unknown node type: {spec.type!r}")


def make_default_agent_fn() -> Callable[..., Awaitable[Any]]:
    """Factory that returns the production agent runner. Imported lazily so
    Claude SDK is not required for tests using FunctionRunner only."""
    from vnstock_bot.research.agent import run_agent

    async def _runner(
        user_prompt: str,
        system_prompt: str,
        tool_names: list[str],
        max_turns: int | None,
    ) -> Any:
        return await run_agent(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            tool_names=tool_names,
            max_turns=max_turns,
        )

    return _runner
