import pytest

from vnstock_bot.orchestrator import NodeContext, NodeSpec, register_function
from vnstock_bot.orchestrator.nodes import (
    AgentRunner,
    FunctionRunner,
    _clear_registry_for_tests,
    get_function,
    make_runner,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


async def test_register_and_lookup_function():
    @register_function("my_fn")
    async def _fn(ctx):
        return {"ok": True}

    fn = get_function("my_fn")
    assert fn is _fn


async def test_register_duplicate_raises():
    @register_function("dup")
    async def _a(ctx):
        return 1

    with pytest.raises(ValueError):
        register_function("dup")(lambda ctx: 2)


async def test_unknown_function_raises():
    with pytest.raises(KeyError):
        get_function("ghost")


async def test_function_runner_executes_with_kwargs():
    @register_function("add")
    async def _add(*, ctx: NodeContext, delta: int = 1):
        return ctx.variables["base"] + delta

    spec = NodeSpec(id="a", type="function", function="add",
                    function_kwargs={"delta": 5})
    runner = FunctionRunner(spec=spec)
    ctx = NodeContext(node_id="a", variables={"base": 10})
    assert await runner.run(ctx) == 15


async def test_agent_runner_calls_injected_agent_fn():
    calls = []

    async def fake_agent(*, user_prompt, system_prompt, tool_names, max_turns):
        calls.append((user_prompt, tuple(tool_names)))
        from types import SimpleNamespace
        return SimpleNamespace(text="ok", turns=3, tokens_used=1234)

    spec = NodeSpec(
        id="chat",
        type="agent",
        tools=["load_skill"],
        prompt_template="Hello {name}",
        system_prompt="You are a bot",
    )
    runner = AgentRunner(spec=spec, agent_fn=fake_agent)
    ctx = NodeContext(node_id="chat", variables={"name": "FPT"})
    out = await runner.run(ctx)
    assert out == {"text": "ok", "turns": 3, "tokens_used": 1234}
    assert calls == [("Hello FPT", ("load_skill",))]


async def test_agent_runner_without_agent_fn_raises():
    spec = NodeSpec(id="chat", type="agent", prompt_template="x")
    runner = AgentRunner(spec=spec, agent_fn=None)
    ctx = NodeContext(node_id="chat")
    with pytest.raises(RuntimeError, match="not wired"):
        await runner.run(ctx)


def test_make_runner_routes_by_type():
    fn_spec = NodeSpec(id="f", type="function", function="noop")
    ag_spec = NodeSpec(id="a", type="agent")
    assert isinstance(make_runner(fn_spec), FunctionRunner)
    assert isinstance(make_runner(ag_spec), AgentRunner)


async def test_safe_template_preserves_unknown_placeholders():
    @register_function("echo")
    async def _echo(*, ctx: NodeContext):
        return {}

    # Agent template with a placeholder not in variables → should be preserved
    # verbatim, NOT raise KeyError.
    async def fake_agent(*, user_prompt, system_prompt, tool_names, max_turns):
        from types import SimpleNamespace
        return SimpleNamespace(text=user_prompt, turns=1, tokens_used=0)

    spec = NodeSpec(id="c", type="agent",
                    prompt_template="Hello {unknown_var}")
    runner = AgentRunner(spec=spec, agent_fn=fake_agent)
    out = await runner.run(NodeContext(node_id="c"))
    assert out["text"] == "Hello {unknown_var}"
