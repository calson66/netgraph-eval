"""Trace schema: one JSON line per run (one question, one config, one repeat).

Only tool calls, tool results and visible assistant text are recorded; no hidden reasoning
(thinking mode is switched off in configs/models.yaml).
Raw traces in results/raw/ are append-only; every table and figure is derived from them.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class Step(BaseModel):
    idx: int
    tool: str
    args: dict
    result_summary: str
    status: str                 # ok | error
    error_type: str | None = None
    latency_ms: int


class QueryRecord(BaseModel):
    query: str
    status: str
    error_type: str | None = None
    rows: list[dict] = []       # at most 50 rows, kept so grading can compare with the gold result
    truncated: bool = False


class FinalAnswer(BaseModel):
    answer_text: str = ""
    answer_values: list = []
    cannot_answer: bool = False


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class Trace(BaseModel):
    run_id: str
    qid: str
    config: str                 # agent | direct
    model: str
    prompt_version: str
    condition: str = "normal"   # normal | prompt_degraded | schema_changed | model_swap
    repeat_idx: int = 0
    steps: list[Step] = []
    queries: list[QueryRecord] = []
    assistant_text: list[str] = []
    final: FinalAnswer = FinalAnswer()
    final_parsed: bool = True   # False if the model's final reply was not valid JSON
    terminated_reason: str = "final"   # final | max_steps | error
    n_llm_calls: int = 0
    usage: Usage = Usage()
    latency_ms: int = 0
    cost_usd: float = 0.0
    error: str | None = None    # set if the run crashed (e.g. API error)
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def make_run_id(qid: str, config: str, model: str, prompt_version: str, condition: str,
                repeat_idx: int) -> str:
    return f"{qid}|{config}|{model}|{prompt_version}|{condition}|{repeat_idx}"


def summarize(result: dict, max_chars: int = 300) -> str:
    if result.get("status") != "ok":
        return f"{result.get('error_type')}: {result.get('message', '')}"[:max_chars]
    if "rows" in result:
        text = f"{len(result['rows'])} rows: {json.dumps(result['rows'], default=str)}"
        return text[:max_chars]
    return json.dumps(result, default=str)[:max_chars]


def parse_final(text: str | None) -> tuple[FinalAnswer, bool]:
    """Find the JSON object in the model's final reply. Returns (answer, parsed_ok)."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match:
        try:
            return FinalAnswer.model_validate(json.loads(match.group(0))), True
        except ValueError:
            pass
    return FinalAnswer(answer_text=text or ""), False


def append_trace(trace: Trace, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(trace.model_dump_json() + "\n")


def load_traces(path: Path) -> list[Trace]:
    if not path.exists():
        return []
    return [Trace.model_validate_json(line) for line in path.read_text().splitlines() if line]
