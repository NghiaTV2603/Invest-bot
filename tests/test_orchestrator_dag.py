import asyncio

import pytest

from vnstock_bot.orchestrator import (
    DagSpec,
    NodeSpec,
    load_trace,
    register_function,
    run_dag,
)
from vnstock_bot.orchestrator.nodes import _clear_registry_for_tests


@pytest.fixture(autouse=True)
def _clear_registry():
    _clear_registry_for_tests()
    yield
    _clear_registry_for_tests()


def _fn_node(nid: str, fn_name: str, **kw) -> NodeSpec:
    return NodeSpec(id=nid, type="function", function=fn_name, **kw)


async def test_linear_dag_success():
    @register_function("step_a")
    async def _a(ctx):
        return {"a": 1}

    @register_function("step_b")
    async def _b(ctx):
        return {"b": ctx.upstream["prev"]["a"] + 1}

    spec = DagSpec(
        name="linear",
        nodes=[
            _fn_node("a", "step_a"),
            _fn_node("b", "step_b", depends_on=["a"],
                     input_from={"prev": "a"}),
        ],
    )
    result = await run_dag(spec, persist=False)
    assert result.status == "success"
    assert result.node("a").output == {"a": 1}
    assert result.node("b").output == {"b": 2}
    assert result.final_output == {"b": 2}


async def test_parallel_nodes_execute_concurrently():
    events: list[str] = []

    @register_function("slow_a")
    async def _a(ctx):
        events.append("a_start")
        await asyncio.sleep(0.05)
        events.append("a_end")
        return {"a": True}

    @register_function("slow_b")
    async def _b(ctx):
        events.append("b_start")
        await asyncio.sleep(0.05)
        events.append("b_end")
        return {"b": True}

    spec = DagSpec(name="par",
                   nodes=[_fn_node("a", "slow_a"), _fn_node("b", "slow_b")])
    result = await run_dag(spec, persist=False)
    assert result.status == "success"
    # Both should have started before either finished
    assert events.index("a_start") < events.index("a_end")
    assert events.index("b_start") < events.index("b_end")
    # Concurrency: b_start must happen before a_end (or vice versa)
    assert (events.index("a_start") < events.index("b_end") and
            events.index("b_start") < events.index("a_end"))


async def test_node_failure_skips_dependents():
    @register_function("ok")
    async def _ok(ctx):
        return {"ok": True}

    @register_function("boom")
    async def _boom(ctx):
        raise RuntimeError("nope")

    spec = DagSpec(
        name="fail",
        nodes=[
            _fn_node("a", "boom"),
            _fn_node("b", "ok", depends_on=["a"]),
        ],
    )
    result = await run_dag(spec, persist=False)
    assert result.node("a").status == "failed"
    assert result.node("b").status == "skipped"
    assert result.status == "failed"


async def test_node_timeout_marked_timeout():
    @register_function("slow")
    async def _slow(ctx):
        await asyncio.sleep(1.0)
        return {"late": True}

    spec = DagSpec(
        name="to",
        nodes=[_fn_node("a", "slow", timeout_seconds=0)],
    )
    # timeout_seconds=0 → immediate timeout via wait_for
    # (but pydantic allows 0; wait_for(..., 0) fires immediately)
    # Use small positive instead
    spec.nodes[0].timeout_seconds = 1
    # reduce actual work to force timeout
    # patch the registered function to sleep longer than 1s
    _clear_registry_for_tests()

    @register_function("slow_long")
    async def _sl(ctx):
        await asyncio.sleep(2.0)

    spec = DagSpec(
        name="to2",
        nodes=[_fn_node("a", "slow_long", timeout_seconds=1)],
    )
    result = await run_dag(spec, persist=False)
    assert result.node("a").status == "timeout"
    assert result.status == "failed"


async def test_dag_timeout_marks_remaining_nodes():
    @register_function("slow_dag")
    async def _s(ctx):
        await asyncio.sleep(5)

    spec = DagSpec(
        name="dag_to",
        timeout_seconds=1,
        nodes=[_fn_node("a", "slow_dag", timeout_seconds=10)],
    )
    result = await run_dag(spec, persist=False)
    assert result.status == "timeout"
    assert result.node("a").status == "timeout"


async def test_streaming_listener_gets_all_events():
    @register_function("ok")
    async def _ok(ctx):
        return {}

    events: list[str] = []

    async def listener(ev):
        events.append(f"{ev.type}:{ev.node_id or '-'}")

    spec = DagSpec(name="s",
                   nodes=[_fn_node("a", "ok"), _fn_node("b", "ok",
                                                        depends_on=["a"])])
    await run_dag(spec, listeners=[listener], persist=False)
    assert events[0].startswith("dag_start")
    assert events[-1].startswith("dag_end")
    assert "node_start:a" in events
    assert "node_end:a" in events
    assert "node_start:b" in events
    assert "node_end:b" in events


async def test_listener_exception_does_not_break_run():
    @register_function("ok")
    async def _ok(ctx):
        return {}

    async def bad_listener(_):
        raise RuntimeError("boom")

    spec = DagSpec(name="x", nodes=[_fn_node("a", "ok")])
    result = await run_dag(spec, listeners=[bad_listener], persist=False)
    assert result.status == "success"


async def test_persist_writes_trace_rows():
    @register_function("ok")
    async def _ok(ctx):
        return {"v": 1}

    spec = DagSpec(name="persist_test", nodes=[_fn_node("a", "ok")])
    result = await run_dag(spec, persist=True)
    loaded = load_trace(result.trace_id)
    assert loaded is not None
    assert loaded["preset"] == "persist_test"
    assert loaded["status"] == "success"
    assert len(loaded["nodes"]) == 1
    assert loaded["nodes"][0]["status"] == "success"
    assert loaded["nodes"][0]["output"] == {"v": 1}


async def test_input_from_missing_upstream_skips_node():
    @register_function("ok")
    async def _ok(ctx):
        return {"ok": True}

    @register_function("boom")
    async def _boom(ctx):
        raise RuntimeError("x")

    spec = DagSpec(
        name="skip_input_from",
        nodes=[
            _fn_node("a", "boom"),
            _fn_node("b", "ok"),
            _fn_node("c", "ok", depends_on=["a", "b"],
                     input_from={"up": "a"}),
        ],
    )
    result = await run_dag(spec, persist=False)
    # c has two deps: a (failed) and b (success). Should be skipped.
    assert result.node("c").status == "skipped"
