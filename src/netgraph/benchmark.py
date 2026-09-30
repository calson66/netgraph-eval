"""Benchmark question schema and loader.

A question's gold answer is never hand-written: `scripts/make_benchmark.py` runs `gold_cypher`
and stores the result in `gold_result`. Ambiguous questions also carry `alt_results`, one per
reading of the question; an answer matching any of them (or the full gold_result) counts as correct.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

BENCHMARK_PATH = Path(__file__).resolve().parents[2] / "data" / "benchmark.jsonl"

Category = Literal["lookup", "filter_agg", "multi_hop", "impact", "unanswerable"]
AnswerRule = Literal["set", "list", "number", "refuse"]


class Question(BaseModel):
    qid: str
    question: str
    category: Category
    difficulty: Literal["easy", "medium", "hard"]
    answer_rule: AnswerRule
    gold_cypher: str | None = None
    gold_result: list | float | int | None = None
    alt_cyphers: list[str] = []
    alt_results: list[list] = []
    notes: str = ""

    @property
    def ambiguous(self) -> bool:
        return bool(self.alt_cyphers)

    @model_validator(mode="after")
    def check_consistency(self):
        if (self.category == "unanswerable") != (self.answer_rule == "refuse"):
            raise ValueError(f"{self.qid}: refuse rule <=> unanswerable category")
        if self.answer_rule != "refuse" and not self.gold_cypher:
            raise ValueError(f"{self.qid}: answerable question needs gold_cypher")
        return self


def load_benchmark(path: Path = BENCHMARK_PATH) -> list[Question]:
    return [Question.model_validate_json(line) for line in path.read_text().splitlines() if line]


def save_benchmark(questions: list[Question], path: Path = BENCHMARK_PATH) -> None:
    lines = [json.dumps(q.model_dump(), ensure_ascii=False) for q in questions]
    path.write_text("\n".join(lines) + "\n")
