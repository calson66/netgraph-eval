"""Build data/benchmark.jsonl from data/benchmark_src.yaml by executing every gold query.

Also writes docs/benchmark_review.md: the questions listed in data/review_log.csv with their gold
query and result, for manual checking in Neo4j Browser.
Usage:  uv run python scripts/make_benchmark.py            # (re)generate
        uv run python scripts/make_benchmark.py --freeze   # after review: record file hash
"""

import csv
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from netgraph.benchmark import BENCHMARK_PATH, Question, load_benchmark, save_benchmark
from netgraph.db import get_driver

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "benchmark_src.yaml"
REVIEW_LOG = ROOT / "data" / "review_log.csv"
REVIEW_SHEET = ROOT / "docs" / "benchmark_review.md"
MANIFEST = ROOT / "results" / "manifests" / "benchmark_manifest.json"


def run_gold(session, query: str, rule: str):
    """Run a one-column gold query. number -> single value; set -> sorted list; list -> as is."""
    records = session.run(query).values()
    if records and len(records[0]) != 1:
        raise ValueError(f"gold query must return one column: {query}")
    values = [r[0] for r in records]
    if rule == "number":
        if len(values) != 1:
            raise ValueError(f"number rule needs exactly one row, got {values}: {query}")
        return values[0]
    return sorted(values) if rule == "set" else values


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> list[Question]:
    driver = get_driver()
    questions = []
    with driver.session() as session:
        for item in yaml.safe_load(SRC.read_text()):
            q = Question(**item)
            if q.gold_cypher:
                q.gold_result = run_gold(session, q.gold_cypher, q.answer_rule)
            q.alt_results = [run_gold(session, c, q.answer_rule) for c in q.alt_cyphers]
            questions.append(q)
    driver.close()
    return questions


def write_review_sheet(questions: list[Question]) -> None:
    by_id = {q.qid: q for q in questions}
    with REVIEW_LOG.open() as f:
        qids = [row["qid"] for row in csv.DictReader(f)]
    parts = ["# Benchmark review sheet\n",
             "For each question: run the Cypher in Neo4j Browser, check that the query really "
             "answers the question and the result matches. Record ok=1/0 and a comment in "
             "`data/review_log.csv`.\n"]
    for qid in qids:
        q = by_id[qid]
        parts.append(f"## {q.qid} ({q.category}, {q.difficulty})\n\n**Q:** {q.question}\n")
        if q.gold_cypher:
            parts.append(f"```cypher\n{q.gold_cypher}\n```\n")
        parts.append(f"**gold_result** (`{q.answer_rule}`): `{json.dumps(q.gold_result)}`\n")
        for cypher, res in zip(q.alt_cyphers, q.alt_results, strict=True):
            parts.append(f"Alternative reading:\n```cypher\n{cypher}\n```\n→ `{json.dumps(res)}`\n")
        if q.notes:
            parts.append(f"_Notes: {q.notes}_\n")
    REVIEW_SHEET.write_text("\n".join(parts))


def freeze() -> None:
    questions = load_benchmark()
    MANIFEST.write_text(json.dumps({
        "file": "data/benchmark.jsonl", "sha256": sha256(BENCHMARK_PATH),
        "n_questions": len(questions), "frozen_on": date.today().isoformat(),
    }, indent=2) + "\n")
    print(f"Frozen: {MANIFEST.relative_to(ROOT)}")


def main() -> None:
    if "--freeze" in sys.argv:
        freeze()
        return
    questions = build()
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text())["sha256"]
        save_benchmark(questions, BENCHMARK_PATH.with_suffix(".tmp"))
        new = sha256(BENCHMARK_PATH.with_suffix(".tmp"))
        BENCHMARK_PATH.with_suffix(".tmp").unlink()
        if new != old:
            sys.exit("Benchmark is frozen and the result would change. Delete the manifest "
                     "only if you really mean to change the frozen benchmark.")
    save_benchmark(questions)
    write_review_sheet(questions)
    counts = {}
    for q in questions:
        counts[q.category] = counts.get(q.category, 0) + 1
    print(f"Wrote {len(questions)} questions: {counts}")
    print(f"Ambiguous: {[q.qid for q in questions if q.ambiguous]}")


if __name__ == "__main__":
    main()
