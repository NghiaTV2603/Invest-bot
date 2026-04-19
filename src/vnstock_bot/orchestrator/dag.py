"""Async DAG runner.

Execution model:
- Toposort nodes into levels (waves). Nodes at the same level run in parallel
  via `asyncio.gather`. Waves run sequentially.
- Per-node timeout via `asyncio.wait_for`. Timeout marks the node `timeout`
  and propagates as skipped downstream dependents.
- Per-DAG timeout via an outer `asyncio.wait_for` around the whole run.
- If a node fails, its dependents are marked `skipped` (not rerun, not executed).
  The DAG's status becomes `partial` (some node done, some skipped) or
  `failed` (nothing usable).
- Every run records one `dag_traces` row + one `dag_node_results` row per node.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.orchestrator.nodes import (
    NodeContext,
    NodeRunner,
    make_runner,
)
from vnstock_bot.orchestrator.streaming import EventBus, OnEvent
from vnstock_bot.orchestrator.types import (
    DagResult,
    DagSpec,
    NodeResult,
    NodeSpec,
)

log = get_logger(__name__)


# ---------------------------------------------------------------- topology

def _topo_levels(spec: DagSpec) -> list[list[NodeSpec]]:
    """Kahn's algorithm → list of waves. Raises ValueError on cycles."""
    by_id = {n.id: n for n in spec.nodes}
    in_deg: dict[str, int] = {n.id: len(n.depends_on) for n in spec.nodes}
    children: dict[str, list[str]] = defaultdict(list)
    for n in spec.nodes:
        for dep in n.depends_on:
            children[dep].append(n.id)

    levels: list[list[NodeSpec]] = []
    ready: deque[str] = deque([nid for nid, d in in_deg.items() if d == 0])
    visited = 0
    while ready:
        wave_ids: list[str] = list(ready)
        ready.clear()
        levels.append([by_id[i] for i in wave_ids])
        for nid in wave_ids:
            visited += 1
            for child in children[nid]:
                in_deg[child] -= 1
                if in_deg[child] == 0:
                    ready.append(child)

    if visited != len(spec.nodes):
        unresolved = [nid for nid, d in in_deg.items() if d > 0]
        raise ValueError(f"cycle detected; unresolved nodes: {unresolved}")
    return levels


# ---------------------------------------------------------------- persistence

def _persist_dag_start(trace_id: str, spec: DagSpec, variables: dict, started: str) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO dag_traces (trace_id, preset, status, started_at,
                                       variables_json)
               VALUES (?, ?, 'running', ?, ?)""",
            (trace_id, spec.name, started, json.dumps(variables, ensure_ascii=False)),
        )


def _persist_dag_end(result: DagResult) -> None:
    with transaction() as conn:
        conn.execute(
            """UPDATE dag_traces
               SET status = ?, ended_at = ?, elapsed_ms = ?, final_output_json = ?
               WHERE trace_id = ?""",
            (
                result.status,
                result.ended_at,
                result.elapsed_ms,
                json.dumps(result.final_output, ensure_ascii=False, default=str)
                if result.final_output is not None else None,
                result.trace_id,
            ),
        )


def _persist_node_result(trace_id: str, res: NodeResult) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO dag_node_results
                (trace_id, node_id, status, started_at, ended_at,
                 elapsed_ms, output_json, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trace_id,
                res.node_id,
                res.status,
                res.started_at,
                res.ended_at,
                res.elapsed_ms,
                json.dumps(res.output, ensure_ascii=False, default=str)
                if res.output is not None else None,
                res.error,
            ),
        )


# ---------------------------------------------------------------- execution

async def _run_single_node(
    spec: NodeSpec,
    runner: NodeRunner,
    variables: dict[str, Any],
    prior_results: dict[str, NodeResult],
    trace_id: str,
    bus: EventBus,
) -> NodeResult:
    started = now_vn()
    started_iso = started.isoformat()

    # Resolve upstream inputs per NodeSpec.input_from
    upstream: dict[str, Any] = {}
    for local_key, src_id in spec.input_from.items():
        src = prior_results.get(src_id)
        if src is None or src.status != "success":
            return NodeResult(
                node_id=spec.id,
                status="skipped",
                error=f"upstream {src_id} not available",
                started_at=started_iso,
                ended_at=started_iso,
                elapsed_ms=0,
            )
        upstream[local_key] = src.output

    ctx = NodeContext(
        node_id=spec.id,
        variables=variables,
        upstream=upstream,
        trace_id=trace_id,
    )

    await bus.emit(trace_id, "node_start", node_id=spec.id,
                   data={"type": spec.type})

    try:
        output = await asyncio.wait_for(
            runner.run(ctx), timeout=spec.timeout_seconds
        )
        ended = now_vn()
        res = NodeResult(
            node_id=spec.id,
            status="success",
            output=output,
            started_at=started_iso,
            ended_at=ended.isoformat(),
            elapsed_ms=int((ended - started).total_seconds() * 1000),
        )
        await bus.emit(
            trace_id, "node_end", node_id=spec.id,
            data={"elapsed_ms": res.elapsed_ms},
        )
        return res
    except TimeoutError:
        ended = now_vn()
        res = NodeResult(
            node_id=spec.id,
            status="timeout",
            error=f"timed out after {spec.timeout_seconds}s",
            started_at=started_iso,
            ended_at=ended.isoformat(),
            elapsed_ms=int((ended - started).total_seconds() * 1000),
        )
        await bus.emit(trace_id, "node_fail", node_id=spec.id,
                       data={"reason": "timeout"})
        return res
    except Exception as exc:  # noqa: BLE001
        ended = now_vn()
        res = NodeResult(
            node_id=spec.id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            started_at=started_iso,
            ended_at=ended.isoformat(),
            elapsed_ms=int((ended - started).total_seconds() * 1000),
        )
        await bus.emit(trace_id, "node_fail", node_id=spec.id,
                       data={"reason": res.error})
        return res


async def run_dag(
    spec: DagSpec,
    variables: dict[str, Any] | None = None,
    *,
    agent_fn: Callable | None = None,
    listeners: list[OnEvent] | None = None,
    trace_id: str | None = None,
    persist: bool = True,
) -> DagResult:
    """Execute a DAG and return a `DagResult`.

    Arguments:
        spec: validated DagSpec.
        variables: user-supplied DAG inputs (e.g., {"ticker": "FPT"}).
        agent_fn: injected async callable for AgentRunner. If None, agent
            nodes will fail at run time with a clear error.
        listeners: streaming event callbacks.
        trace_id: optional externally-provided trace id (for idempotent
            replay). If None, a fresh UUID is generated.
        persist: write to dag_traces + dag_node_results tables. Disable in
            pure-logic tests that don't init the DB.
    """
    variables = variables or {}
    trace_id = trace_id or str(uuid.uuid4())
    bus = EventBus(listeners)

    started = now_vn()
    started_iso = started.isoformat()

    if persist:
        _persist_dag_start(trace_id, spec, variables, started_iso)
    await bus.emit(trace_id, "dag_start",
                   data={"preset": spec.name, "variables": variables})

    node_results: dict[str, NodeResult] = {}
    runners: dict[str, NodeRunner] = {
        n.id: make_runner(n, agent_fn=agent_fn) for n in spec.nodes
    }

    async def _exec_all() -> None:
        for wave in _topo_levels(spec):
            # Skip any node whose dependency already failed / skipped.
            active: list[NodeSpec] = []
            for n in wave:
                dep_fail = any(
                    node_results.get(d) is None
                    or node_results[d].status != "success"
                    for d in n.depends_on
                )
                if dep_fail:
                    skipped = NodeResult(
                        node_id=n.id,
                        status="skipped",
                        error="dependency did not succeed",
                        started_at=now_vn().isoformat(),
                        ended_at=now_vn().isoformat(),
                    )
                    node_results[n.id] = skipped
                    if persist:
                        _persist_node_result(trace_id, skipped)
                else:
                    active.append(n)

            if not active:
                continue

            results = await asyncio.gather(*[
                _run_single_node(
                    spec=n,
                    runner=runners[n.id],
                    variables=variables,
                    prior_results=node_results,
                    trace_id=trace_id,
                    bus=bus,
                )
                for n in active
            ])
            for r in results:
                node_results[r.node_id] = r
                if persist:
                    _persist_node_result(trace_id, r)

    try:
        await asyncio.wait_for(_exec_all(), timeout=spec.timeout_seconds)
        dag_status = _rollup_status(spec, node_results)
        dag_error: str | None = None
    except TimeoutError:
        # Mark any not-yet-completed nodes as timeout
        for n in spec.nodes:
            if n.id not in node_results:
                node_results[n.id] = NodeResult(
                    node_id=n.id,
                    status="timeout",
                    error="dag timeout",
                    started_at=started_iso,
                    ended_at=now_vn().isoformat(),
                )
                if persist:
                    _persist_node_result(trace_id, node_results[n.id])
        dag_status = "timeout"
        dag_error = f"dag exceeded {spec.timeout_seconds}s"

    ended = now_vn()
    # Final output = last topological node's output if successful
    last_nodes = _topo_levels(spec)[-1] if spec.nodes else []
    final_output: Any = None
    if last_nodes:
        last = last_nodes[-1]
        last_res = node_results.get(last.id)
        if last_res and last_res.status == "success":
            final_output = last_res.output

    result = DagResult(
        trace_id=trace_id,
        preset=spec.name,
        status=dag_status,
        started_at=started_iso,
        ended_at=ended.isoformat(),
        elapsed_ms=int((ended - started).total_seconds() * 1000),
        variables=variables,
        node_results=node_results,
        final_output=final_output,
        error=dag_error,
    )
    if persist:
        _persist_dag_end(result)
    await bus.emit(trace_id, "dag_end",
                   data={"status": dag_status, "elapsed_ms": result.elapsed_ms})
    log.info("dag_done", preset=spec.name, trace_id=trace_id, status=dag_status,
             elapsed_ms=result.elapsed_ms,
             success_count=sum(1 for r in node_results.values() if r.status == "success"),
             total=len(spec.nodes))
    return result


def _rollup_status(spec: DagSpec, results: dict[str, NodeResult]) -> str:
    succeeded = [r for r in results.values() if r.status == "success"]
    if len(succeeded) == len(spec.nodes):
        return "success"
    if not succeeded:
        return "failed"
    return "partial"


# ---------------------------------------------------------------- replay / introspection

def load_trace(trace_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM dag_traces WHERE trace_id = ?", (trace_id,)
    ).fetchone()
    if not row:
        return None
    node_rows = conn.execute(
        """SELECT * FROM dag_node_results
           WHERE trace_id = ?
           ORDER BY started_at""",
        (trace_id,),
    ).fetchall()
    return {
        "trace_id": row["trace_id"],
        "preset": row["preset"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "elapsed_ms": row["elapsed_ms"],
        "variables": json.loads(row["variables_json"] or "{}"),
        "final_output": json.loads(row["final_output_json"]) if row["final_output_json"] else None,
        "nodes": [
            {
                "node_id": r["node_id"],
                "status": r["status"],
                "started_at": r["started_at"],
                "ended_at": r["ended_at"],
                "elapsed_ms": r["elapsed_ms"],
                "output": json.loads(r["output_json"]) if r["output_json"] else None,
                "error": r["error"],
            }
            for r in node_rows
        ],
    }
