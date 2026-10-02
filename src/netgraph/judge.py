"""LLM judge: is the final answer faithful to the last query result? (no gold answer needed)

This is a label-free signal that could run in production. The judge sees the question, the last
query and its result rows, and the answer; it returns {"faithful": bool, "reason": str}.
Verdicts are cached append-only in results/raw/judge_<exp>.jsonl, keyed by run_id.
"""

import json
from pathlib import Path

from netgraph import llm
from netgraph.trace import Trace

JUDGE_VERSION = "judge_v1"
MAX_RESULT_CHARS = 4000

PROMPT = """You check whether an answer is faithful to a database query result.

Question: {question}
Last Cypher query: {query}
Query result: {result}
Answer given: {answer}

The answer is FAITHFUL if every fact in it is supported by the query result, or if it correctly
says the information is not available because the result is empty, errored, or no query was run.
It is NOT faithful if it states facts, numbers or IDs that are not in the result, or contradicts it.
Do not judge whether the query itself was the right query; only whether the answer follows from it.

Reply with only: {{"faithful": true|false, "reason": "<one short sentence>"}}"""


def judge_prompt(question: str, t: Trace) -> str:
    last = t.queries[-1] if t.queries else None
    if last is None:
        result, query = "(no query was run)", "(none)"
    elif last.status != "ok":
        result, query = f"error: {last.error_type}", last.query
    else:
        result = json.dumps(last.rows, default=str)[:MAX_RESULT_CHARS]
        result += " (truncated)" if last.truncated else ""
        query = last.query
    answer = json.dumps(t.final.model_dump(), default=str)
    return PROMPT.format(question=question, query=query, result=result, answer=answer)


def judge(question: str, t: Trace, model: str | None = None) -> dict:
    model = model or llm.load_config("models.yaml")["models"]["judge"]
    resp = llm.chat([{"role": "user", "content": judge_prompt(question, t)}], model=model)
    try:
        start, end = resp.text.index("{"), resp.text.rindex("}") + 1
        verdict = json.loads(resp.text[start:end])
        faithful = bool(verdict["faithful"])
        reason = str(verdict.get("reason", ""))
    except (ValueError, KeyError, AttributeError):
        faithful, reason = None, f"unparseable judge reply: {resp.text!r}"[:300]
    return {"run_id": t.run_id, "judge_version": JUDGE_VERSION, "judge_model": model,
            "faithful": faithful, "reason": reason, "cost_usd": resp.cost_usd,
            "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens}


def judge_all(traces: list[Trace], questions: dict, path: Path) -> dict[str, dict]:
    """Judge every trace not yet in the cache file; return {run_id: verdict}."""
    cache = {}
    if path.exists():
        cache = {v["run_id"]: v for v in map(json.loads, path.read_text().splitlines()) if v}
    with path.open("a") as f:
        for t in traces:
            if t.run_id in cache or t.error:
                continue
            verdict = judge(questions[t.qid].question, t)
            cache[t.run_id] = verdict
            f.write(json.dumps(verdict) + "\n")
            f.flush()
    return cache
