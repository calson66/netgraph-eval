"""Analyse the two manual-review sheets once they are filled in.

Failure spot-check: how often the reviewer agrees with the rule-based failure stage.
Human ratings (single rater, exploratory): Spearman correlation of correctness/usefulness with
automatic metrics, and agreement of the LLM judge / automatic grading with the human.
Usage: uv run python scripts/analyze_reviews.py
"""

from pathlib import Path

import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]


def spotcheck() -> None:
    df = pd.read_csv(ROOT / "data" / "failure_spotcheck.csv")
    done = df[df["agree"].notna()]
    if done.empty:
        print("failure_spotcheck.csv: not filled in yet")
        return
    agree = done["agree"].astype(str).str.strip().str.lower().isin(["1", "yes", "y", "true"])
    print(f"Failure spot-check: reviewer agrees with the rule on {agree.sum()}/{len(done)} runs")
    cols = ["run_id", "rule_stage", "your_stage", "comment"]
    print(done.loc[~agree, cols].to_string(index=False))


def ratings() -> None:
    df = pd.read_csv(ROOT / "data" / "human_ratings.csv")
    done = df[df["correctness"].notna()]
    if done.empty:
        print("human_ratings.csv: not filled in yet")
        return
    key = pd.read_csv(ROOT / "results" / "manifests" / "rating_key.csv")
    graded = pd.read_csv(ROOT / "results" / "tables" / "graded_main.csv")
    m = done.merge(key, on="rating_id").merge(graded, on="run_id")
    rows = []
    for human in ["correctness", "usefulness"]:
        for auto in ["answer_correct", "faithful", "n_llm_calls", "tokens", "cost_usd"]:
            sub = m[[human, auto]].dropna()
            rho, p = spearmanr(sub[human].astype(float), sub[auto].astype(float))
            rows.append({"human": human, "automatic": auto, "n": len(sub),
                         "spearman_rho": round(rho, 3), "p_value": round(p, 4)})
    out = pd.DataFrame(rows)
    human_ok = m["correctness"].astype(float) == 2
    agreement = {
        "auto answer_correct vs human (correctness == 2)": (m["answer_correct"] == human_ok).mean(),
        "LLM judge faithful vs human (correctness == 2)": (m["faithful"] == human_ok).mean(),
    }
    out.to_csv(ROOT / "results" / "tables" / "human_ratings_analysis.csv", index=False)
    print(f"Human ratings ({len(m)} runs, ONE rater - exploratory):")
    print(out.to_string(index=False))
    for k, v in agreement.items():
        print(f"{k}: {v:.2f}")


if __name__ == "__main__":
    spotcheck()
    print()
    ratings()
