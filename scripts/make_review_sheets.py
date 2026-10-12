"""Export the two manual-review sheets (the reviewer fills the empty columns).

data/failure_spotcheck.csv : 10 failed main runs -> does the rule-based failure stage look right?
data/human_ratings.csv     : 30 runs, stratified (configs, correct/wrong, categories), config
                             hidden; rate correctness and usefulness 0-2.
The rating_id -> run_id key goes to results/manifests/rating_key.csv (do not open while rating).
Usage: uv run python scripts/make_review_sheets.py   (refuses to overwrite filled sheets)
"""

import json
from pathlib import Path

import pandas as pd

from netgraph.benchmark import load_benchmark
from netgraph.trace import load_traces

ROOT = Path(__file__).resolve().parents[1]
SEED = 7


def tool_summary(t) -> str:
    if not t.queries:
        return "(no query run)"
    parts = []
    for i, r in enumerate(t.queries, 1):
        rows = json.dumps(r.rows)[:160]
        result = r.error_type if r.status != "ok" else f"{len(r.rows)} rows {rows}"
        parts.append(f"[{i}] {' '.join(r.query.split())}  ->  {result}")
    return "\n".join(parts)


def answer(t) -> str:
    f = t.final
    if f.cannot_answer:
        return "CANNOT ANSWER: " + f.answer_text
    return f"{f.answer_text} {f.answer_values}"


def main() -> None:
    questions = {q.qid: q for q in load_benchmark()}
    traces = {t.run_id: t for t in load_traces(ROOT / "results" / "raw" / "main.jsonl")}
    graded = pd.read_csv(ROOT / "results" / "tables" / "graded_main.csv")
    gold = {q.qid: ("REFUSE (not in the data)" if q.answer_rule == "refuse"
                    else json.dumps(q.gold_result)) for q in questions.values()}

    def rows_for(df):
        return [{"qid": r.qid, "question": questions[r.qid].question, "gold_answer": gold[r.qid],
                 "queries_and_results": tool_summary(traces[r.run_id]),
                 "final_answer": answer(traces[r.run_id])} for r in df.itertuples()]

    # 1) failure spot-check: 10 failed runs, all agent failures + direct failures over many qids
    spot_path = ROOT / "data" / "failure_spotcheck.csv"
    fails = graded[~graded["answer_correct"]]
    agent_f = fails[fails["config"] == "agent"].drop_duplicates("qid")
    direct_f = fails[fails["config"] == "direct"].drop_duplicates("qid")
    direct_f = direct_f.sample(min(10 - len(agent_f), len(direct_f)), random_state=SEED)
    spot = pd.concat([agent_f, direct_f])
    spot_df = pd.DataFrame(rows_for(spot)).assign(
        run_id=spot["run_id"].values, rule_stage=spot["failure_stage"].values,
        your_stage="", agree="", comment="")
    if spot_path.exists() and pd.read_csv(spot_path)["agree"].notna().any():
        print(f"{spot_path.name} already filled, not overwritten")
    else:
        spot_df.to_csv(spot_path, index=False)

    # 2) blind human ratings: 15 wrong + 15 correct, both configs, categories spread
    rate_path = ROOT / "data" / "human_ratings.csv"
    agent_wrong = fails[fails["config"] == "agent"]                      # all 6
    direct_wrong = (fails[fails["config"] == "direct"]
                    .sample(frac=1, random_state=SEED)
                    .sort_values("qid", kind="stable")
                    .drop_duplicates("qid").head(15 - len(agent_wrong)))   # distinct questions
    wrong = pd.concat([agent_wrong, direct_wrong])
    right = graded[graded["answer_correct"] & (graded["repeat_idx"] == 0)]
    right = (right.sample(frac=1, random_state=SEED)
             .drop_duplicates(["config", "category"])     # one per config x category
             .pipe(lambda d: pd.concat([d, right.drop(d.index).sample(5, random_state=SEED)])))
    picked = pd.concat([wrong, right]).sample(frac=1, random_state=SEED).reset_index(drop=True)
    ratings = pd.DataFrame(rows_for(picked))
    ratings.insert(0, "rating_id", [f"R{i + 1:02d}" for i in range(len(ratings))])
    ratings = ratings.drop(columns="qid").assign(correctness="", usefulness="", comment="")
    if rate_path.exists() and pd.read_csv(rate_path)["correctness"].notna().any():
        print(f"{rate_path.name} already filled, not overwritten")
    else:
        ratings.to_csv(rate_path, index=False)
        pd.DataFrame({"rating_id": ratings["rating_id"], "run_id": picked["run_id"]}).to_csv(
            ROOT / "results" / "manifests" / "rating_key.csv", index=False)
    print(f"spot-check: {len(spot_df)} runs; ratings: {len(ratings)} runs "
          f"({int((~picked['answer_correct']).sum())} wrong, "
          f"{picked['config'].value_counts().to_dict()})")


if __name__ == "__main__":
    main()
