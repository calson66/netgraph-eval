"""Rebuild every table and figure from the raw traces (results/raw/) — nothing is hand-edited.

Steps: load traces -> LLM-judge any run not yet judged (cached, append-only) -> grade ->
write results/tables/*.csv and results/figures/*.png.
Usage: uv run python scripts/make_report_assets.py [--exp main] [--no-judge]
"""

import argparse
from pathlib import Path

import pandas as pd

from netgraph import analysis
from netgraph.benchmark import load_benchmark
from netgraph.grading import grade
from netgraph.judge import judge_all
from netgraph.trace import load_traces

ROOT = Path(__file__).resolve().parents[1]
RAW, TABLES, FIGURES = (ROOT / "results" / d for d in ("raw", "tables", "figures"))


def graded_frame(exp: str, use_judge: bool) -> pd.DataFrame:
    questions = {q.qid: q for q in load_benchmark()}
    traces = load_traces(RAW / f"{exp}.jsonl")
    verdicts = judge_all(traces, questions, RAW / f"judge_{exp}.jsonl") if use_judge else {}
    rows = []
    for t in traces:
        g = grade(questions[t.qid], t)
        v = verdicts.get(t.run_id, {})
        g["faithful"] = v.get("faithful")
        g["judge_cost_usd"] = v.get("cost_usd", 0.0)
        rows.append(g)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", default="main")
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    graded = graded_frame(args.exp, use_judge=not args.no_judge)
    graded.to_csv(TABLES / f"graded_{args.exp}.csv", index=False)
    table = analysis.main_table(graded)
    table.to_csv(TABLES / f"{args.exp}.csv", index=False)
    analysis.plot_failure_stages(graded, FIGURES / "failure_stages.png")
    analysis.plot_accuracy_vs_cost(graded, FIGURES / "accuracy_vs_cost.png")

    with pd.option_context("display.width", 200, "display.max_columns", 30):
        print(table[table["category"] == "ALL"].T.to_string(header=False))
    print(f"\nJudge cost: ${graded['judge_cost_usd'].sum():.4f}; "
          f"runs cost: ${graded['cost_usd'].sum():.4f}")


if __name__ == "__main__":
    main()
