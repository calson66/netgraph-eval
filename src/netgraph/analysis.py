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


# ---------- Phase 5: label-free monitoring signals ----------

SIGNALS = ["query_error_rate", "empty_result_rate", "hit_limit_rate", "avg_llm_calls",
           "avg_tokens", "unfaithful_rate", "refusal_rate"]


def signals(df: pd.DataFrame) -> dict:
    """Signals that need no gold answer, so they could be computed on live traffic."""
    n_q = max(df["n_queries"].sum(), 1)
    return {
        "query_error_rate": df["n_query_errors"].sum() / n_q,
        "empty_result_rate": df["n_empty_results"].sum() / n_q,
        "hit_limit_rate": df["hit_limit"].mean(),
        "avg_llm_calls": df["n_llm_calls"].mean(),
        "avg_tokens": df["tokens"].mean(),
        "unfaithful_rate": (df["faithful"] == False).mean(),  # noqa: E712 (None = not judged)
        "refusal_rate": df["cannot_answer"].mean(),
    }


def degradation_table(normal: pd.DataFrame, degraded: pd.DataFrame) -> pd.DataFrame:
    """Rows = conditions. A signal alarms if it leaves mean ± 2·SD of the normal repeats."""
    per_repeat = pd.DataFrame([signals(g) for _, g in normal.groupby("repeat_idx")])
    mean, sd = per_repeat.mean(), per_repeat.std(ddof=1)
    acc_normal = normal.groupby("repeat_idx")["answer_correct"].mean()
    rows = [{"condition": "normal (mean of 3 repeats)", "runs": len(normal),
             "accuracy": round(acc_normal.mean(), 3), "accuracy_change": 0.0,
             **{s: round(mean[s], 3) for s in SIGNALS},
             **{f"{s}_band": f"±{2 * sd[s]:.3f}" for s in SIGNALS}}]
    for cond, g in degraded.groupby(["config", "condition"], sort=False):
        sig = signals(g)
        row = {"condition": f"{cond[1]} ({cond[0]})", "runs": len(g),
               "accuracy": round(g["answer_correct"].mean(), 3),
               "accuracy_change": round(g["answer_correct"].mean() - acc_normal.mean(), 3)}
        for s in SIGNALS:
            row[s] = round(sig[s], 3)
            alarm = abs(sig[s] - mean[s]) > 2 * sd[s] if sd[s] > 0 else sig[s] != mean[s]
            row[f"{s}_alarm"] = bool(alarm)
        row["n_alarms"] = sum(row[f"{s}_alarm"] for s in SIGNALS)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------- Phase 5: escalation and value ----------

def escalate(df: pd.DataFrame) -> pd.Series:
    """Hand the run to a human if any label-free warning sign fires."""
    return (df["last_query_error"]
            | (~df["cannot_answer"] & df["last_query_empty"])
            | df["hit_limit"]
            | (df["faithful"] == False))  # noqa: E712


def value_row(df: pd.DataFrame, minutes: dict) -> dict:
    esc = escalate(df)
    wrong = ~df["answer_correct"]
    mins = df["category"].map(minutes)
    net = mins[df["answer_correct"]].sum() - minutes["wrong_unescalated_penalty"] * mins[
        wrong & ~esc].sum()
    tokens, n_ok = df["tokens"].sum(), int(df["answer_correct"].sum())
    return {
        "runs": len(df),
        "accuracy": round(df["answer_correct"].mean(), 3),
        "tokens_per_success": round(tokens / n_ok) if n_ok else None,
        "cost_per_success_usd": round(df["cost_usd"].sum() / n_ok, 5) if n_ok else None,
        "net_value_minutes_per_run": round(net / len(df), 2),
        "value_per_1k_tokens": round(net / (tokens / 1000), 3),
        "escalation_rate": round(esc.mean(), 3),
        "escalation_precision": round((esc & wrong).sum() / esc.sum(), 3) if esc.sum() else None,
        "escalation_recall": round((esc & wrong).sum() / wrong.sum(), 3) if wrong.sum() else None,
        "cost_per_run_usd": round(df["cost_usd"].mean(), 5),
    }


ROUTE_TO_AGENT = {"multi_hop", "impact"}


def routed(main: pd.DataFrame) -> pd.DataFrame:
    """Illustrative oracle router: category is known in advance (it would need a classifier)."""
    pick = main["category"].isin(ROUTE_TO_AGENT).map({True: "agent", False: "direct"})
    return main[main["config"] == pick].assign(config="router (oracle category)")


def decision_table(main: pd.DataFrame, minutes: dict) -> pd.DataFrame:
    frames = [g for _, g in main.groupby("config", sort=False)] + [routed(main)]
    return pd.DataFrame([{"config": f["config"].iloc[0], **value_row(f, minutes)}
                         for f in frames])


def plot_value_vs_cost(decision: pd.DataFrame, path) -> None:
    fig, ax = plt.subplots(figsize=(6, 4), facecolor=COLORS["surface"])
    colors = [CONFIG_COLOR.get(c, COLORS["series"][2]) for c in decision["config"]]
    for (_, r), color in zip(decision.iterrows(), colors, strict=True):
        x, y = r["cost_per_run_usd"] * 1000, r["net_value_minutes_per_run"]
        ax.scatter(x, y, s=80, color=color, zorder=3, edgecolor=COLORS["surface"], linewidth=2)
        below = r["config"].startswith("router")       # avoid colliding with the agent label
        ax.annotate(f"{r['config']}\n{y:.1f} min/run, acc {r['accuracy']:.0%}", (x, y),
                    textcoords="offset points", xytext=(0, -34) if below else (10, -6),
                    ha="center" if below else "left", fontsize=9, color=COLORS["text"])
    ax.set_xlim(0, decision["cost_per_run_usd"].max() * 1000 * 1.8)
    ax.set_ylim(0, decision["net_value_minutes_per_run"].max() * 1.25)
    ax.set_xlabel("cost per run (USD × 10⁻³, peak price)")
    ax.set_ylabel("net analyst minutes saved per run (assumed)")
    ax.set_title("Value vs cost (minutes are an assumption, see configs/)", loc="left",
                 fontsize=11, color=COLORS["text"])
    _style(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
