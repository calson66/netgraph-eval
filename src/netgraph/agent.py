"""ReAct-style Text-to-Cypher agent, written as a plain loop (no agent framework).

Each iteration: call the LLM with the conversation so far and two tools (get_schema, run_cypher).
If it asks for tools, run them and append the results; if it replies without a tool call, that
reply is the final JSON answer. Limits: 8 LLM calls and 4 run_cypher calls per question.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

from netgraph import db, llm
from netgraph.trace import QueryRecord, Step, Trace, Usage, make_run_id, parse_final, summarize

PROMPT_DIR = Path(__file__).resolve().parents[2] / "configs" / "prompts"
MAX_STEPS = 8
MAX_QUERIES = 4

TOOLS = [
    {"name": "get_schema",
     "description": "Return the graph schema: node labels with properties, relationship "
                    "patterns, and the allowed values of categorical properties.",
     "parameters": {"type": "object", "properties": {}, "required": []}},
    {"name": "run_cypher",
     "description": "Run one read-only Cypher query and return up to 50 rows, or an error.",
     "parameters": {"type": "object",
                    "properties": {"query": {"type": "string", "description": "Cypher query"}},
                    "required": ["query"]}},
]


class ToolBox:
    """The agent's access to the database. Tests replace it with a fake."""

    def __init__(self, driver):
        self.driver = driver

    def get_schema(self) -> dict:
        return db.get_schema(self.driver)

    def run_cypher(self, query: str) -> dict:
        return db.run_readonly(self.driver, query)


def run_agent(qid: str, question: str, tools: ToolBox, model: str, prompt_version: str = "agent_v1",
              condition: str = "normal", repeat_idx: int = 0,
              chat: Callable[..., llm.LLMResponse] = llm.chat) -> Trace:
    system = (PROMPT_DIR / f"{prompt_version}.txt").read_text()
    trace = Trace(run_id=make_run_id(qid, "agent", model, prompt_version, condition, repeat_idx),
                  qid=qid, config="agent", model=model, prompt_version=prompt_version,
                  condition=condition, repeat_idx=repeat_idx)
    messages: list[dict] = [{"role": "user", "content": question}]
    start = time.perf_counter()
    usage = Usage()
    n_queries = 0

    try:
        for _ in range(MAX_STEPS):
            resp = chat(messages, system=system, tools=TOOLS, model=model)
            trace.n_llm_calls += 1
            usage.input_tokens += resp.input_tokens
            usage.output_tokens += resp.output_tokens
            trace.cost_usd += resp.cost_usd

            if not resp.tool_calls:             # no tool call -> this is the final answer
                trace.final, trace.final_parsed = parse_final(resp.text)
                trace.terminated_reason = "final"
                break

            if resp.text:                       # visible text before a tool call
                trace.assistant_text.append(resp.text)
            messages.append({"role": "assistant", "content": resp.text,
                             "tool_calls": resp.tool_calls})

            for call in resp.tool_calls:
                t0 = time.perf_counter()
                if call.name == "get_schema":
                    result = {"status": "ok", "schema": tools.get_schema()}
                elif call.name == "run_cypher" and "query" not in call.args:
                    result = {"status": "error", "error_type": "bad_arguments",
                              "message": "run_cypher needs a 'query' argument."}
                elif call.name == "run_cypher" and n_queries >= MAX_QUERIES:
                    result = {"status": "error", "error_type": "query_limit",
                              "message": f"Query limit ({MAX_QUERIES}) reached. Answer now."}
                elif call.name == "run_cypher":
                    n_queries += 1
                    result = tools.run_cypher(call.args["query"])
                    trace.queries.append(QueryRecord(
                        query=call.args["query"], status=result["status"],
                        error_type=result.get("error_type"), rows=result.get("rows", []),
                        truncated=result.get("truncated", False)))
                else:
                    result = {"status": "error", "error_type": "unknown_tool",
                              "message": f"No tool named {call.name}."}

                trace.steps.append(Step(
                    idx=len(trace.steps), tool=call.name, args=call.args,
                    result_summary=summarize(result), status=result["status"],
                    error_type=result.get("error_type"),
                    latency_ms=int((time.perf_counter() - t0) * 1000)))
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(result, default=str)})
        else:
            trace.terminated_reason = "max_steps"
    except Exception as e:  # API failure etc.: keep the partial trace instead of losing the run
        trace.terminated_reason = "error"
        trace.error = f"{type(e).__name__}: {e}"

    trace.usage = usage
    trace.latency_ms = int((time.perf_counter() - start) * 1000)
    return trace
