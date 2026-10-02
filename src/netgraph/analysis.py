"""Aggregate graded runs into tables and figures.

Confidence intervals: bootstrap over QUESTIONS (resample qids with replacement, keep all repeats
of a sampled question), 2000 resamples, fixed seed -> 95% percentile interval.
Colors: validated categorical slots from the dataviz reference palette (light mode).
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SEED = 0
N_BOOT = 2000
STAGES = ["schema_grounding", "query_generation", "trajectory", "answer_synthesis"]
COLORS = {"series": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"],
          "text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "surface": "#fcfcfb"}
CONFIG_COLOR = {"direct": COLORS["series"][1], "agent": COLORS["series"][0]}


def bootstrap_ci(df: pd.DataFrame, col: str, stat=np.mean) -> tuple[float, float]:
    rng = np.random.default_rng(SEED)
    groups = [g[col].to_numpy(dtype=float) for _, g in df.groupby("qid")]
    if not groups:
        return (np.nan, np.nan)
    stats = []
    for _ in range(N_BOOT):
        picks = rng.integers(0, len(groups), len(groups))
        stats.append(stat(np.concatenate([groups[i] for i in picks])))
    return tuple(np.percentile(stats, [2.5, 97.5]))


def fmt_ci(df, col):
    lo, hi = bootstrap_ci(df, col)
    return f"{df[col].mean():.2f} [{lo:.2f}, {hi:.2f}]"


def pass_all_repeats(df: pd.DataFrame) -> float:
    """Share of questions answered correctly in EVERY repeat (pass^k, k = number of repeats)."""
    return df.groupby("qid")["answer_correct"].all().mean()


def summary_row(df: pd.DataFrame) -> dict:
    answerable = df[df["category"] != "unanswerable"]
    fails = df[~df["answer_correct"]]
    n_correct = int(df["answer_correct"].sum())
    row = {
        "runs": len(df),
        "answer_correct": fmt_ci(df, "answer_correct"),
        "exec_correct (answerable)": fmt_ci(answerable, "exec_correct") if len(answerable) else "",
        "pass^k": round(pass_all_repeats(df), 2),
        "avg_llm_calls": round(df["n_llm_calls"].mean(), 2),
        "avg_queries": round(df["n_queries"].mean(), 2),
        "avg_tokens": round(df["tokens"].mean()),
        "cost_per_run_usd": round(df["cost_usd"].mean(), 5),
        "cost_per_success_usd": round(df["cost_usd"].sum() / n_correct, 5) if n_correct else None,
        "avg_latency_s": round(df["latency_ms"].mean() / 1000, 1),
        "n_failures": len(fails),
    }
    for stage in STAGES:
        row[f"fail_{stage}"] = int((fails["failure_stage"] == stage).sum())
    return row


def main_table(graded: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for config, g in graded.groupby("config", sort=False):
        rows.append({"config": config, "category": "ALL", **summary_row(g)})
        for cat, gc in g.groupby("category", sort=False):
            rows.append({"config": config, "category": cat, **summary_row(gc)})
    return pd.DataFrame(rows)


def _style(ax):
    ax.set_facecolor(COLORS["surface"])
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(COLORS["grid"])
    ax.tick_params(colors=COLORS["muted"], labelsize=9)
    ax.yaxis.label.set_color(COLORS["muted"])
    ax.xaxis.label.set_color(COLORS["muted"])
    ax.grid(axis="y", color=COLORS["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def plot_failure_stages(graded: pd.DataFrame, path) -> None:
    configs = list(dict.fromkeys(graded["config"]))
    fig, ax = plt.subplots(figsize=(6, 4), facecolor=COLORS["surface"])
    bottoms = np.zeros(len(configs))
    for stage, color in zip(STAGES, COLORS["series"], strict=True):
        counts = np.array([((graded["config"] == c) & (graded["failure_stage"] == stage)).sum()
                           for c in configs])
        ax.bar(configs, counts, bottom=bottoms, color=color, width=0.5, label=stage,
               edgecolor=COLORS["surface"], linewidth=2)
        bottoms += counts
    for x, total in enumerate(bottoms):
        ax.text(x, total + 0.5, f"{int(total)} failed runs", ha="center", va="bottom",
                fontsize=9, color=COLORS["text"])
    ax.set_ylim(0, max(bottoms.max(), 1) * 1.15)
    ax.set_ylabel(f"failed runs (out of {len(graded) // len(configs)} per config)")
    ax.set_title("Where do wrong answers come from?", loc="left", fontsize=11,
                 color=COLORS["text"], pad=12)
    ax.legend(frameon=False, fontsize=8, labelcolor=COLORS["text"],
              loc="upper left", bbox_to_anchor=(1, 1))
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_accuracy_vs_cost(graded: pd.DataFrame, path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4), facecolor=COLORS["surface"])
    for config, g in graded.groupby("config", sort=False):
        acc = g["answer_correct"].mean()
        lo, hi = bootstrap_ci(g, "answer_correct")
        cost = g["cost_usd"].mean() * 1000
        clo, chi = bootstrap_ci(g, "cost_usd")
        color = CONFIG_COLOR.get(config, COLORS["series"][2])
        ax.errorbar(cost, acc, yerr=[[acc - lo], [hi - acc]],
                    xerr=[[cost - clo * 1000], [chi * 1000 - cost]],
                    fmt="o", markersize=9, color=color, ecolor=color, elinewidth=2, capsize=0)
        ax.annotate(f"{config}\n{acc:.0%} correct, ${g['cost_usd'].mean():.4f}/run",
                    (cost, acc), textcoords="offset points", xytext=(10, -4),
                    fontsize=9, color=COLORS["text"])
    ax.set_xlabel("cost per run (USD × 10⁻³, peak price)")
    ax.set_ylabel("answer accuracy")
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, graded.groupby("config")["cost_usd"].mean().max() * 1000 * 1.7)
    ax.set_title("Accuracy vs cost (95% bootstrap CI over questions)", loc="left",
                 fontsize=11, color=COLORS["text"])
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
