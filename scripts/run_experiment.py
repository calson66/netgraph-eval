"""Run agent and/or direct configs on benchmark questions; append traces to results/raw/<exp>.jsonl.

Resumable: runs whose run_id is already in the file are skipped (raw traces are never rewritten).
Writes a manifest (configs, prompt texts, benchmark hash, git commit) to results/manifests/.
Usage:  uv run python scripts/run_experiment.py --exp pilot --pilot
        uv run python scripts/run_experiment.py --exp main --repeats 3
"""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from netgraph import llm
from netgraph.agent import PROMPT_DIR, ToolBox, run_agent
from netgraph.baseline import run_direct
from netgraph.benchmark import BENCHMARK_PATH, load_benchmark
from netgraph.db import get_driver
from netgraph.trace import append_trace, load_traces, make_run_id

ROOT = Path(__file__).resolve().parents[1]
PILOT_QIDS = ["L01", "L09", "F02", "F08", "M01", "M05", "I01", "I05", "U01", "U08"]


def write_manifest(exp: str, args: argparse.Namespace) -> None:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    manifest = {
        "exp": exp, "started": datetime.now(UTC).isoformat(), "args": vars(args),
        "git_commit": commit,
        "benchmark_sha256": hashlib.sha256(BENCHMARK_PATH.read_bytes()).hexdigest(),
        "models_yaml": llm.load_config("models.yaml"),
        "pricing_yaml": llm.load_config("pricing.yaml"),
        "prompts": {p.name: p.read_text() for p in sorted(PROMPT_DIR.glob("*.txt"))},
    }
    path = ROOT / "results" / "manifests" / f"{exp}_{manifest['started'][:19]}.json"
    path.write_text(json.dumps(manifest, indent=2, default=str) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, help="experiment name -> results/raw/<exp>.jsonl")
    ap.add_argument("--configs", default="direct,agent")
    ap.add_argument("--qids", default="", help="comma-separated; default all 50")
    ap.add_argument("--pilot", action="store_true", help="use the 10 pilot questions")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--model", default="main", help="key in models.yaml: main | degraded")
    ap.add_argument("--condition", default="normal")
    ap.add_argument("--agent-prompt", default="agent_v1")
    ap.add_argument("--direct-prompt", default="direct_v1")
    args = ap.parse_args()

    model = llm.load_config("models.yaml")["models"][args.model]
    questions = load_benchmark()
    wanted = PILOT_QIDS if args.pilot else [q for q in args.qids.split(",") if q]
    if wanted:
        questions = [q for q in questions if q.qid in wanted]

    out = ROOT / "results" / "raw" / f"{args.exp}.jsonl"
    done = {t.run_id for t in load_traces(out)}
    write_manifest(args.exp, args)
    driver = get_driver()
    tools = ToolBox(driver)
    spent = 0.0
    n_run = 0

    for repeat in range(args.repeats):
        for q in questions:
            for config in args.configs.split(","):
                prompt = args.agent_prompt if config == "agent" else args.direct_prompt
                run_id = make_run_id(q.qid, config, model, prompt, args.condition, repeat)
                if run_id in done:
                    continue
                runner = run_agent if config == "agent" else run_direct
                trace = runner(q.qid, q.question, tools, model, prompt_version=prompt,
                               condition=args.condition, repeat_idx=repeat)
                append_trace(trace, out)
                spent += trace.cost_usd
                n_run += 1
                flag = f" ERROR {trace.error}" if trace.error else ""
                print(f"[{n_run}] {q.qid} {config:<6} r{repeat} {trace.terminated_reason:<9} "
                      f"calls={trace.n_llm_calls} q={len(trace.queries)} "
                      f"${trace.cost_usd:.4f} -> {trace.final.answer_values}{flag}")

    driver.close()
    print(f"\n{n_run} new runs, ${spent:.4f} this invocation. Traces: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
