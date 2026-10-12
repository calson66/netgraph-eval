"""Rebuild every table and figure from the raw traces (results/raw/) — nothing is hand-edited.

Steps: load traces -> LLM-judge any run not yet judged (cached, append-only) -> grade ->
write results/tables/*.csv and results/figures/*.png. Phase 5 tables are added when
results/raw/degradation.jsonl exists.
Usage: uv run python scripts/make_report_assets.py [--no-judge]
"""

import argparse
from pathlib import Path

import pandas as pd

from netgraph import analysis, llm
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
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()
    use_judge = not args.no_judge
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    def show():
        return pd.option_context("display.width", 220, "display.max_columns", 40)

    # Phase 4: main experiment
    main_df = graded_frame("main", use_judge)
    main_df.to_csv(TABLES / "graded_main.csv", index=False)
    table = analysis.main_table(main_df)
    table.to_csv(TABLES / "main.csv", index=False)
    analysis.plot_failure_stages(main_df, FIGURES / "failure_stages.png")
    analysis.plot_accuracy_vs_cost(main_df, FIGURES / "accuracy_vs_cost.png")
    with show():
        print(table[table["category"] == "ALL"].T.to_string(header=False))

    # Phase 5c: value and decision table (from the main experiment)
    minutes = llm.load_config("value_minutes.yaml")
    decision = analysis.decision_table(main_df, minutes)
    decision.to_csv(TABLES / "decision.csv", index=False)
    analysis.plot_value_vs_cost(decision, FIGURES / "value_vs_cost.png")
    with show():
        print("\n" + decision.to_string(index=False))

    # Phase 5a/b: degradation detection
    total_judge = main_df["judge_cost_usd"].sum()
    total_runs = main_df["cost_usd"].sum()
    if (RAW / "degradation.jsonl").exists():
        deg = graded_frame("degradation", use_judge)
        deg.to_csv(TABLES / "graded_degradation.csv", index=False)
        normal = main_df[main_df["config"] == "agent"]
        detection = analysis.degradation_table(normal, deg)
        detection.to_csv(TABLES / "degradation_detection.csv", index=False)
        with show():
            print("\n" + detection.T.to_string(header=False))
        total_judge += deg["judge_cost_usd"].sum()
        total_runs += deg["cost_usd"].sum()

    print(f"\nRun cost ${total_runs:.4f}; judge cost ${total_judge:.4f}")


if __name__ == "__main__":
    main()
