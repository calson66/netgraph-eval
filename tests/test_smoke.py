"""Phase 0 smoke tests.

- Offline tests (always run): read-only guard, message-format conversion.
- `neo4j` tests need `docker compose up -d`; `llm` test makes one tiny paid API call.
  Skip them with: uv run pytest -m "not neo4j and not llm"
"""

import os

import pytest

from netgraph import db, llm


@pytest.mark.parametrize("query", [
    "CREATE (n:X)", "MATCH (n) DETACH DELETE n", "MATCH (n) SET n.a = 1",
    "merge (n:X {id: 1})", "LOAD CSV FROM 'x' AS row RETURN row", "CALL dbms.components()",
])
def test_write_queries_are_forbidden(query):
    assert db.is_forbidden(query)


@pytest.mark.parametrize("query", [
    "MATCH (d:Device) RETURN count(d)",
    "MATCH (s:Site {name: 'SET-01 Created'}) RETURN s",  # keyword inside a string is fine
    "MATCH (d:Device) WHERE d.status = 'failed' RETURN d.id AS offset_id",
])
def test_read_queries_are_allowed(query):
    assert not db.is_forbidden(query)


def test_tool_results_grouped_for_anthropic():
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": None,
         "tool_calls": [llm.ToolCall("a", "get_schema", {}), llm.ToolCall("b", "x", {})]},
        {"role": "tool", "tool_call_id": "a", "content": "r1"},
        {"role": "tool", "tool_call_id": "b", "content": "r2"},
    ]
    out = llm.to_anthropic_messages(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert len(out[2]["content"]) == 2


@pytest.fixture(scope="module")
def driver():
    d = db.get_driver()
    yield d
    d.close()


@pytest.mark.neo4j
def test_neo4j_connects_and_reads(driver):
    res = db.run_readonly(driver, "RETURN 1 AS x")
    assert res == {"status": "ok", "rows": [{"x": 1}], "truncated": False}


@pytest.mark.neo4j
def test_neo4j_errors_are_structured(driver):
    res = db.run_readonly(driver, "MATCH (n RETURN n")
    assert res["status"] == "error" and res["error_type"] == "syntax"
    assert db.run_readonly(driver, "CREATE (n:X)")["error_type"] == "forbidden"


@pytest.mark.neo4j
def test_rows_are_capped(driver):
    res = db.run_readonly(driver, "UNWIND range(1, 200) AS i RETURN i")
    assert len(res["rows"]) == db.MAX_ROWS and res["truncated"]


@pytest.mark.llm
def test_llm_call_records_tokens():
    cfg = llm.load_config("models.yaml")
    key = cfg["providers"][cfg["provider"]]["api_key_env"]
    if not os.environ.get(key):
        pytest.skip(f"{key} not set")
    r = llm.chat([{"role": "user", "content": "Reply with the single word: pong"}])
    assert r.text and "pong" in r.text.lower()
    assert r.input_tokens > 0 and r.output_tokens > 0 and r.latency_ms > 0
    print(f"\n{r.model}: {r.input_tokens} in / {r.output_tokens} out, ${r.cost_usd:.6f}")
