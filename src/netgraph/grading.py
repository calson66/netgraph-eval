"""Grade one trace against its benchmark question: per-stage metrics and failure attribution.

Pure functions (no database, no LLM): everything is computed from the trace and the question.
Stages: schema grounding -> query generation -> trajectory -> answer synthesis.
Failure attribution is a heuristic rule list (see `attribute_failure`), not ground truth.
"""

import json
import re
from pathlib import Path

from netgraph.benchmark import Question
from netgraph.trace import QueryRecord, Trace

SCHEMA_SNAPSHOT = Path(__file__).resolve().parents[2] / "configs" / "schema_snapshot.json"


# ---------- value comparison ----------

def norm(v):
    """Make values comparable: numbers as float, strings trimmed and case-folded."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        try:
            return float(s)
        except ValueError:
            return s.casefold()
    return json.dumps(v, sort_keys=True, default=str)


def matches(values: list, q: Question) -> bool:
    """Do these values answer q under its answer_rule (or under one ambiguous reading)?"""
    vals = [norm(v) for v in values]
    if q.answer_rule == "number":
        return len(vals) == 1 and vals[0] == norm(q.gold_result)
    candidates = [q.gold_result] + q.alt_results
    if q.answer_rule == "set":
        return any(set(vals) == {norm(v) for v in c} for c in candidates)
    if q.answer_rule == "list":
        return any(vals == [norm(v) for v in c] for c in candidates)
    return False


def answer_correct(q: Question, t: Trace) -> bool:
    if q.answer_rule == "refuse":
        return t.final.cannot_answer
    return (not t.final.cannot_answer) and matches(t.final.answer_values, q)


def rows_match(rec: QueryRecord, q: Question) -> bool:
    """Does any single column of the query result equal the gold answer?"""
    if rec.status != "ok" or not rec.rows or q.answer_rule == "refuse":
        return False
    columns = {k: [row.get(k) for row in rec.rows] for k in rec.rows[0]}
    for col in columns.values():
        if len(col) == 1 and isinstance(col[0], list):   # e.g. RETURN collect(c.id)
            col = col[0]
        if q.answer_rule == "set":                        # DISTINCT, keep order
            seen = {}
            for v in col:
                seen.setdefault(norm(v), v)
            col = list(seen.values())
        if matches(col, q):
            return True
    return False


# ---------- schema elements in a query ----------

def schema_elements(query: str) -> dict[str, set]:
    """Labels, relationship types and property keys used in a Cypher query (regex, approximate)."""
    q = re.sub(r"'[^']*'|\"[^\"]*\"", "''", query)            # drop string literals
    labels = set(re.findall(r"\(\s*\w*\s*:\s*`?(\w+)", q))
    rels = set()
    for group in re.findall(r"\[\s*\w*\s*:\s*([\w|:`]+)", q):
        rels |= {r for r in re.split(r"[|:`]+", group) if r}
    props = set(re.findall(r"\b[a-z_]\w*\.([a-z_]\w*)", q))      # n.prop (lower-case keys)
    for body in re.findall(r"\{([^{}]*)\}", q):
        if "(" not in body:                                     # a property map, not a subquery
            props |= set(re.findall(r"(\w+)\s*:", body))
    return {"labels": labels, "rels": rels, "props": props}


def load_schema_sets(schema: dict | None = None) -> dict[str, set]:
    schema = schema or json.loads(SCHEMA_SNAPSHOT.read_text())
    props = {p for ps in schema["nodes"].values() for p in ps}
    props |= {p for ps in schema["relationships"].values() for p in ps}
    return {"labels": set(schema["nodes"]), "rels": set(schema["relationships"]), "props": props}


def schema_valid(query: str, schema_sets: dict[str, set]) -> bool:
    used = schema_elements(query)
    return all(used[k] <= schema_sets[k] for k in used)


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def flat(elements: dict[str, set]) -> set:
    return {f"{k}:{v}" for k, vs in elements.items() for v in vs}


# ---------- one trace ----------

def grade(q: Question, t: Trace, schema_sets: dict[str, set] | None = None) -> dict:
    schema_sets = schema_sets or load_schema_sets()
    queries = t.queries
    last = queries[-1] if queries else None
    last_ok = next((r for r in reversed(queries) if r.status == "ok"), None)
    normalized = [re.sub(r"\s+", " ", r.query.strip().lower()) for r in queries]

    g = {
        "run_id": t.run_id, "qid": q.qid, "config": t.config, "model": t.model,
        "prompt_version": t.prompt_version, "condition": t.condition, "repeat_idx": t.repeat_idx,
        "category": q.category, "difficulty": q.difficulty, "ambiguous": q.ambiguous,
        # answer synthesis
        "answer_correct": answer_correct(q, t),
        "cannot_answer": t.final.cannot_answer,
        "final_parsed": t.final_parsed,
        # query generation
        "has_query": last is not None,
        "syntax_valid": last is not None and last.error_type != "syntax",
        "exec_correct": last_ok is not None and rows_match(last_ok, q),
        "any_exec_correct": any(rows_match(r, q) for r in queries),
        "last_query_error": last is not None and last.status != "ok",
        "last_query_empty": last is not None and last.status == "ok" and not last.rows,
        # schema grounding
        "schema_valid": last is None or schema_valid(last.query, schema_sets),
        "any_schema_invalid": any(not schema_valid(r.query, schema_sets) for r in queries),
        "schema_overlap": (jaccard(flat(schema_elements(last.query)),
                                   flat(schema_elements(q.gold_cypher)))
                           if last is not None and q.gold_cypher else None),
        # trajectory
        "n_steps": len(t.steps),
        "n_queries": len(queries),
        "n_llm_calls": t.n_llm_calls,
        "repeated_query": len(normalized) != len(set(normalized)),
        "hit_limit": t.terminated_reason == "max_steps"
                     or any(s.error_type == "query_limit" for s in t.steps),
        "terminated_reason": t.terminated_reason,
        # cost
        "input_tokens": t.usage.input_tokens,
        "output_tokens": t.usage.output_tokens,
        "tokens": t.usage.input_tokens + t.usage.output_tokens,
        "cost_usd": t.cost_usd,
        "latency_ms": t.latency_ms,
        "error": t.error,
    }
    g["failure_stage"] = attribute_failure(q, g)
    return g


def attribute_failure(q: Question, g: dict) -> str | None:
    """First matching stage for a wrong answer (heuristic). None if the answer is correct.

    1 schema_grounding : the final query still uses a label/relationship/property not in the schema
    2 trajectory       : hit the step/query limit, or an earlier query had the right result
                         but the final one did not (drifted away)
    3 query_generation : no query, syntax error, or the final result does not equal the gold answer
    4 answer_synthesis : the final query result was right, but the answer was wrong
    Unanswerable questions have no gold result, so steps 2b/3/4 reduce to answer_synthesis.
    """
    if g["answer_correct"]:
        return None
    if g["error"]:
        return "run_error"
    if g["has_query"] and not g["schema_valid"]:
        return "schema_grounding"
    if g["hit_limit"] or (g["any_exec_correct"] and not g["exec_correct"]):
        return "trajectory"
    if q.answer_rule == "refuse":
        return "answer_synthesis"
    if not g["exec_correct"]:
        return "query_generation"
    return "answer_synthesis"
