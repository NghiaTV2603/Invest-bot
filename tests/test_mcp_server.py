import io
import json

from vnstock_bot.db import queries
from vnstock_bot.mcp.server import TOOLS, handle_request, serve


def test_initialize_returns_capabilities():
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "vnstock-bot"
    assert "tools" in resp["result"]["capabilities"]


def test_tools_list_returns_all_tools():
    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert names == {
        "get_price", "get_portfolio", "search_memory",
        "get_timeline", "recall_similar_decision",
    }


def test_all_tools_are_read_only_by_invariant():
    # Write tools must NOT be in the exposed set
    for t in TOOLS:
        assert t.read_only, f"tool {t.name} is not read_only"


def test_unknown_tool_returns_error():
    resp = handle_request({
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "propose_trade", "arguments": {}},
    })
    assert "error" in resp
    assert "unknown" in resp["error"]["message"].lower()


def test_get_portfolio_call_returns_content():
    queries.set_cash(100_000_000)
    resp = handle_request({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "get_portfolio", "arguments": {}},
    })
    assert "result" in resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["cash_vnd"] == 100_000_000
    assert payload["num_positions"] == 0


def test_get_price_on_unknown_ticker_returns_empty_bars():
    resp = handle_request({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "get_price",
                   "arguments": {"ticker": "GHOST", "days": 10}},
    })
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["ticker"] == "GHOST"
    assert payload["bars"] == []


def test_search_memory_handles_empty_state():
    resp = handle_request({
        "jsonrpc": "2.0", "id": 6, "method": "tools/call",
        "params": {"name": "search_memory",
                   "arguments": {"query": "FPT"}},
    })
    assert "result" in resp


def test_unknown_method():
    resp = handle_request({"jsonrpc": "2.0", "id": 7, "method": "bogus"})
    assert resp["error"]["code"] == -32601


def test_serve_reads_line_by_line():
    stdin = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
    )
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    lines = stdout.getvalue().strip().splitlines()
    assert len(lines) == 2
    resp1 = json.loads(lines[0])
    resp2 = json.loads(lines[1])
    assert resp1["id"] == 1
    assert len(resp2["result"]["tools"]) == 5


def test_malformed_json_returns_parse_error():
    stdin = io.StringIO("not json at all\n")
    stdout = io.StringIO()
    serve(stdin=stdin, stdout=stdout)
    resp = json.loads(stdout.getvalue())
    assert resp["error"]["code"] == -32700
