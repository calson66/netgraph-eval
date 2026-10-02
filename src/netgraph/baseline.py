"""One-shot text-to-Cypher baseline (the "direct" config): no tools, no correction.

1. LLM writes one Cypher query from the question + a STATIC schema snapshot in the prompt.
2. The query is executed once (same read-only executor as the agent).
3. A second LLM call writes the final JSON answer from the query result.
The static snapshot (configs/schema_snapshot.json) goes stale if the database schema changes.
"""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path

from netgraph import llm
from netgraph.agent import PROMPT_DIR, ToolBox
from netgraph.trace import QueryRecord, Step, Trace, Usage, make_run_id, parse_final, summarize

SCHEMA_SNAPSHOT = Path(__file__).resolve().parents[2] / "configs" / "schema_snapshot.json"


def extract_query(text: str | None) -> str | None:
    """Strip code fences; return None if the model said NO_QUERY."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:cypher)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    return None if not text or text.upper().startswith("NO_QUERY") else text


def run_direct(qid: str, question: str, tools: ToolBox, model: str,
               prompt_version: str = "direct_v1", condition: str = "normal",
               repeat_idx: int = 0, chat: Callable[..., llm.LLMResponse] = llm.chat) -> Trace:
    trace = Trace(run_id=make_run_id(qid, "direct", model, prompt_version, condition, repeat_idx),
                  qid=qid, config="direct", model=model, prompt_version=prompt_version,
                  condition=condition, repeat_idx=repeat_idx)
    version = prompt_version.removeprefix("direct_")
    cypher_prompt = (PROMPT_DIR / f"direct_cypher_{version}.txt").read_text()
    answer_prompt = (PROMPT_DIR / f"direct_answer_{version}.txt").read_text()
    start = time.perf_counter()
    usage = Usage()

    def call(messages, system=""):
        resp = chat(messages, system=system, model=model)
        trace.n_llm_calls += 1
        usage.input_tokens += resp.input_tokens
        usage.output_tokens += resp.output_tokens
        trace.cost_usd += resp.cost_usd
        return resp

    try:
        system = cypher_prompt.format(schema=SCHEMA_SNAPSHOT.read_text())
        query = extract_query(call([{"role": "user", "content": question}], system).text)

        if query is None:
            result = {"status": "skipped", "message": "Model replied NO_QUERY."}
        else:
            t0 = time.perf_counter()
            result = tools.run_cypher(query)
            trace.queries.append(QueryRecord(
                query=query, status=result["status"], error_type=result.get("error_type"),
                rows=result.get("rows", []), truncated=result.get("truncated", False)))
            trace.steps.append(Step(
                idx=0, tool="run_cypher", args={"query": query}, result_summary=summarize(result),
                status=result["status"], error_type=result.get("error_type"),
                latency_ms=int((time.perf_counter() - t0) * 1000)))

        prompt = answer_prompt.format(question=question, query=query or "(none)",
                                      result=json.dumps(result, default=str))
        trace.final, trace.final_parsed = parse_final(
            call([{"role": "user", "content": prompt}]).text)
    except Exception as e:
        trace.terminated_reason = "error"
        trace.error = f"{type(e).__name__}: {e}"

    trace.usage = usage
    trace.latency_ms = int((time.perf_counter() - start) * 1000)
    return trace
