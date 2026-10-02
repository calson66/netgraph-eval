"""Phase 3 unit tests for the agent loop and the direct baseline, using a scripted fake LLM.

No database and no API calls: FakeTools stands in for Neo4j, FakeChat replays fixed responses.
Covers: normal finish, hitting the step limit, tool errors, query limit, bad final JSON.
"""

from netgraph.agent import MAX_QUERIES, MAX_STEPS, run_agent
from netgraph.baseline import extract_query, run_direct
from netgraph.llm import LLMResponse, ToolCall


class FakeTools:
    def __init__(self, results=None):
        self.results = results or {}
        self.queries = []

    def get_schema(self):
        return {"nodes": {"Device": ["id", "vendor"]}}

    def run_cypher(self, query):
        self.queries.append(query)
        return self.results.get(query, {"status": "ok", "rows": [{"n": 1}], "truncated": False})


class FakeChat:
    """Returns the scripted responses in order; records what it was sent."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages, system="", tools=None, model=None):
        self.calls.append([dict(m) for m in messages])
        return self.responses.pop(0)


def tool(name, args=None, id_="t"):
    return LLMResponse(None, [ToolCall(id_, name, args or {})], 10, 5, cost_usd=0.001)


def final(json_text):
    return LLMResponse(json_text, [], 10, 5, cost_usd=0.001)


def test_agent_normal_run():
    chat = FakeChat([
        tool("get_schema", id_="a"),
        tool("run_cypher", {"query": "MATCH (d:Device {id:'D-1'}) RETURN d.vendor"}, id_="b"),
        final('{"answer_text": "Nokia", "answer_values": ["Nokia"], "cannot_answer": false}'),
    ])
    t = run_agent("L01", "Which vendor?", FakeTools(), "m", chat=chat)
    assert t.terminated_reason == "final" and t.final_parsed
    assert t.final.answer_values == ["Nokia"]
    assert [s.tool for s in t.steps] == ["get_schema", "run_cypher"]
    assert len(t.queries) == 1 and t.n_llm_calls == 3
    assert t.usage.input_tokens == 30 and abs(t.cost_usd - 0.003) < 1e-9
    # the third LLM call saw both tool results
    assert [m["role"] for m in chat.calls[2]] == ["user", "assistant", "tool", "assistant", "tool"]


def test_agent_hits_step_limit():
    chat = FakeChat([tool("get_schema")] * MAX_STEPS)
    t = run_agent("L01", "q", FakeTools(), "m", chat=chat)
    assert t.terminated_reason == "max_steps"
    assert t.n_llm_calls == MAX_STEPS


def test_agent_sees_tool_error_and_recovers():
    bad = "MATCH (n RETURN n"
    tools = FakeTools({bad: {"status": "error", "error_type": "syntax", "message": "Invalid"}})
    chat = FakeChat([
        tool("run_cypher", {"query": bad}),
        tool("run_cypher", {"query": "MATCH (n) RETURN count(n)"}),
        final('{"answer_text": "1", "answer_values": [1], "cannot_answer": false}'),
    ])
    t = run_agent("F01", "q", tools, "m", chat=chat)
    assert [s.status for s in t.steps] == ["error", "ok"]
    assert t.steps[0].error_type == "syntax"
    assert '"error_type": "syntax"' in chat.calls[1][-1]["content"]  # error was shown to the model
    assert t.final.answer_values == [1]


def test_agent_query_limit():
    chat = FakeChat([tool("run_cypher", {"query": f"RETURN {i}"}) for i in range(MAX_QUERIES + 1)]
                    + [final('{"answer_text": "x", "answer_values": [], "cannot_answer": true}')])
    tools = FakeTools()
    t = run_agent("F01", "q", tools, "m", chat=chat)
    assert len(tools.queries) == MAX_QUERIES
    assert t.steps[-1].error_type == "query_limit"


def test_agent_unparseable_final():
    t = run_agent("U01", "q", FakeTools(), "m", chat=FakeChat([final("I am not sure.")]))
    assert not t.final_parsed and t.final.answer_text == "I am not sure."


def test_agent_api_error_keeps_partial_trace():
    def broken_chat(*a, **k):
        raise RuntimeError("503")
    t = run_agent("L01", "q", FakeTools(), "m", chat=broken_chat)
    assert t.terminated_reason == "error" and "503" in t.error


def test_direct_run():
    chat = FakeChat([
        LLMResponse("```cypher\nMATCH (d:Device) RETURN count(d)\n```", [], 50, 10),
        final('{"answer_text": "138", "answer_values": [138], "cannot_answer": false}'),
    ])
    tools = FakeTools()
    t = run_direct("F01", "How many devices?", tools, "m", chat=chat)
    assert tools.queries == ["MATCH (d:Device) RETURN count(d)"]
    assert t.final.answer_values == [138] and t.n_llm_calls == 2


def test_direct_no_query():
    assert extract_query("NO_QUERY") is None
    chat = FakeChat([LLMResponse("NO_QUERY", [], 50, 2),
                     final('{"answer_text": "n/a", "answer_values": [], "cannot_answer": true}')])
    tools = FakeTools()
    t = run_direct("U01", "Revenue?", tools, "m", chat=chat)
    assert tools.queries == [] and t.final.cannot_answer
