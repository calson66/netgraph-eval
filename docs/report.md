# NetGraph-Eval: where does a Text-to-Cypher agent fail, can we see it degrade, and is it worth it?

*Independent project, Sep–Oct 2026. Synthetic data; not affiliated with KPN. All numbers below are
regenerated from the raw traces by `scripts/make_report_assets.py`; table files are named in brackets.*

## 1. Motivation

Two thesis topics at KPN describe (a) a ReAct-style agent that answers questions over a fixed-network
knowledge graph and (b) metrics that tell whether such agentic systems are worth their cost. This
project builds a small, fully reproducible version of both, to answer three questions:

- **Q1** When the agent fails, which stage fails: schema grounding, query generation, the
  trajectory, or answer synthesis?
- **Q2** If the system is deliberately degraded, which signals that need **no gold answer** notice it?
- **Q3** Measured as cost and value per successful task, is the agent worth it compared with a
  one-shot pipeline?

It does not represent KPN's views, and it uses no KPN data.

## 2. Setup

**Graph.** A synthetic fixed network in Neo4j 5 (seed 42): 592 nodes, 792 relationships. Energy
sources power 20 sites; cabinets house devices; devices form a tree
`core_router → agg_switch → olt → ont`; ONTs deliver services to 98 customers. About 5 % of devices
are not active, four sites have a backup battery, and three site names exist in two cities
(ambiguity). See `docs/schema.md`.

**Benchmark.** 50 questions, 10 per category: `lookup`, `filter_agg`, `multi_hop`, `impact`
(variable-length `FEEDS*` paths) and `unanswerable`; 5 are ambiguous. Every gold answer is produced
by executing a gold Cypher query, never written by hand. I manually checked 20 questions
(20/20 correct) and froze the file (sha256 in `results/manifests/benchmark_manifest.json`).

**Two configurations, same model** (DeepSeek-V4-Pro, thinking mode off, temperature 0), same
schema content, same read-only executor (5 s timeout, 50 rows):

- `direct`: static schema in the prompt → one Cypher query → execute → one answer call.
- `agent`: a hand-written ReAct loop (Yao et al., 2023) with native tool calling and two tools,
  `get_schema()` (live) and `run_cypher(query)`; at most 8 LLM calls and 4 queries.

**Grading.** Answers are compared by execution result (cf. Spider, Yu et al., 2018) under a rule per
question (set / ordered list / number / refuse; any reading counts for ambiguous questions).
Confidence intervals are 95 % bootstrap intervals that resample **questions** (repeats of one
question are not independent). Costs use the provider's peak price, so they are upper bounds.

**Experiments.** Main: 2 configs × 50 questions × 3 repeats = 300 runs. Degradations (agent, 50 runs
each): prompt without the "check schema / fix errors" guidance; schema renamed in the live
database (`Device.status → op_state`, `FEEDS → UPLINKS_TO`, also run for `direct`); a smaller
model (DeepSeek Flash). Total spend: $2.40 for runs + $0.24 for the LLM judge.

## 3. Q1 — Where does the agent fail?

| [main.csv] | `direct` | `agent` |
|---|---|---|
| Answer accuracy (95 % CI) | 0.81 [0.71, 0.91] | **0.96** [0.91, 1.00] |
| `impact` / `multi_hop` accuracy | 0.37 / 0.70 | **0.90 / 0.90** |
| `lookup`, `filter_agg`, `unanswerable` | 1.00 | 1.00 |
| Correct in all 3 repeats (pass^3; Yao et al., 2024) | 0.76 | 0.94 |
| Avg LLM calls / tokens per run | 2.0 / 1,098 | 3.8 / 4,938 |
| Failed runs by stage: schema / query gen. / trajectory / synthesis | 0 / 28 / 0 / 0 | 0 / 1 / 4 / 1 |

Stages are assigned by ordered heuristic rules (`grading.attribute_failure`): a query that uses
unknown schema elements → **schema grounding**; a step/query limit hit or an earlier correct
result that was later abandoned → **trajectory**; no query, a syntax error or a wrong result →
**query generation**; a correct result but a wrong answer → **answer synthesis**.

All 28 `direct` failures are query-generation errors on multi-hop and impact questions: the model
must write a long path correctly in one go. A representative case is M05 ("In which city is the
site that houses the OLT serving customer C-0020?"; pilot trace). Both configs first wrote a query that joined
the customer's service directly to an OLT, which returns 0 rows because services are delivered by
the ONT one hop below. `direct` then answered "cannot answer". The agent saw the empty result,
split the question into three queries (customer → ONT D-0060 → OLT D-0013 → site), and answered
Rotterdam correctly, using 8,151 instead of 1,051 input tokens. The agent's few remaining failures
are mostly trajectory failures (limits reached on long impact questions).

**The LLM judge does not localise these errors.** It was asked whether each answer is faithful to
the last query result. It judged all 34 wrong answers in the main experiment faithful (they
faithfully repeated a wrong result) and flagged 8 correct answers as unfaithful. Answer-level
faithfulness therefore cannot replace stage-level checks.

## 4. Q2 — Which label-free signals detect degradation?

A signal alarms when it leaves the band mean ± 2 SD of the three normal repeats
[degradation_detection.csv].

| Condition (50 runs) | Accuracy Δ | Alarms (of 7) | Signals that alarmed |
|---|---|---|---|
| prompt degraded (agent) | −0.06 | 4 | limit-hit rate 0.08→0.14, LLM calls, tokens, unfaithful rate |
| model swap (agent) | −0.02 | 2 | tokens, unfaithful rate |
| schema changed (agent) | −0.14 | 5 | limit hits 0.24, LLM calls, tokens (+45 %), unfaithful, refusal 0.22→0.32 |
| schema changed (`direct`) | −0.36 | 7 | all, incl. query errors 0.025 and empty results 0.10→0.30 |

What worked: every degradation moved at least two signals, and the number of alarms grew with the
size of the accuracy drop. Under the schema change, the static `direct` pipeline kept using the old
names (14 queries with `FEEDS`, 5 with `status`; 17 schema-grounding failures, impact accuracy 0 %),
which made empty results and refusals jump. The agent read the live schema and never used the old
names (31 of its queries used `UPLINKS_TO`, none `FEEDS` or `status`), but still lost 14 points, mostly via trajectory failures on impact questions;
the new name `UPLINKS_TO` reads as the opposite of the stored direction, which probably misled it.

What did not work: the model swap triggered two alarms although accuracy fell only 2 points —
token count and judge scores detect *change*, not *quality loss*. Query error rate stayed at 0 for
every agent condition, so it is useless here. Three repeats give a very rough band (e.g. ±0.04 for
the limit-hit rate); a production monitor needs a longer baseline and a sequential method such as
CUSUM.

## 5. Q3 — Is the agent worth it?

[decision.csv]. Value minutes are an explicit **assumption** (`configs/value_minutes.yaml`: lookup 2,
filter 5, multi-hop 8, impact 15, unanswerable 3); a wrong answer that is not escalated costs half
its minutes. A run is escalated to a human if its last query failed, it returned an empty result
without refusing, it hit a limit, or the judge called it unfaithful.

| | `direct` | `agent` | router (illustrative) |
|---|---|---|---|
| Accuracy | 0.81 | 0.96 | 0.96 |
| Cost per successful task (USD) | **0.0020** | 0.0075 | 0.0051 |
| Net analyst minutes per run (assumed) | 3.4 | **6.1** | **6.1** |
| Value per 1k tokens | **3.1** | 1.2 | 1.8 |
| Escalation rate / precision / recall | 0.06 / 1.00 / 0.32 | 0.10 / 0.27 / 0.67 | 0.08 / 0.33 / 0.67 |

The agent costs 3.7× more per success and buys +15 points of accuracy, all on multi-hop and impact
questions. Under the assumed minutes it nearly doubles the net value per run, but it is less
token-efficient. Because both configs are perfect on lookup, filter and unanswerable questions, a
router that sends only multi-hop and impact questions to the agent keeps 96 % accuracy at 32 %
lower cost per success. This router is an upper bound: it uses the benchmark category, which a
real system would have to predict. Separately, the agent on the smaller model reached 0.94 at
$0.0020 per success — the same cost as `direct` on the large model (one repeat only).

In this setting the agent is worth it **for the hard questions only**; for simple look-ups the extra
cost buys nothing, which matches the argument of Kapoor et al. (2024) that accuracy must be
reported together with cost.

## 6. Manual review (exploratory, single rater)

One reviewer checked two samples (`scripts/analyze_reviews.py` → `results/tables/human_ratings_analysis.csv`).

**Failure-stage rule, 10 failed runs** (`data/failure_spotcheck.csv`): the reviewer agreed with the
rule on **8/10**. The two disagreements show two blind spots of the heuristic. (1) I07, agent: the
rule says *trajectory* because the query limit was hit, but the root cause was a wrong path (the
query required the service-delivering ONT to sit in a cabinet) repeated twice — a limit hit can
mask a query-generation error. (2) M06, direct: the rule says *query generation*, but the query
invented a `Customer–CONNECTS–Cable` pattern; every name exists, so the name-only schema check
cannot see a non-existent pattern.

**30 blinded runs** (15 wrong, 15 correct; both configs; `data/human_ratings.csv`), rated 0–2:

| Automatic signal vs human | Spearman ρ (correctness) | ρ (usefulness) |
|---|---|---|
| `answer_correct` (automatic grading) | **0.89** (p < 0.001) | **0.82** (p < 0.001) |
| LLM judge `faithful` | −0.18 (p = 0.34) | −0.20 (p = 0.30) |
| LLM calls / tokens / cost | between −0.07 and 0.26, all p > 0.15 | |

Automatic grading agreed with the reviewer's "fully correct" (score 2) on **28/30** runs (0.93); the
LLM judge on **14/30** (0.47), i.e. no better than chance. The two grading disagreements cut both
ways: R29 answered "Rotterdam DC (S-002)" correctly in text but put the site id in
`answer_values`, so automatic grading was too strict; R15 merged the two Stationsplein sites
without saying so, which the union rule accepted but the reviewer scored 1. Effort (steps, tokens,
cost) did not predict quality. With one rater and 30 runs these results are exploratory.

## 7. Limitations and next steps

- **Synthetic, small, tree-shaped graph** (592 nodes, no redundancy); a real network graph has
  cycles, dual uplinks and missing data.
- **50 questions** written by one person; CIs are wide and the agent is near ceiling.
- **One model family**; temperature 0 with thinking mode off.
- **Heuristic failure attribution** with regex-based schema extraction; one cause per failure.
- **Three repeats** for the normal band; degradation conditions ran once.
- **Assumed value minutes**; an oracle router.
- **Single rater** for the manual review.

Next: a real or larger graph, a benchmark with held-out paraphrases, a learned question router,
CUSUM-style drift detection on a longer baseline, and several raters.

## References

- Kapoor, S., Stroebl, B., Siegel, Z. S., Nadgir, N., & Narayanan, A. (2024). *AI Agents That Matter.* arXiv:2407.01502.
- Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023. arXiv:2210.03629.
- Yao, S., Shinn, N., Razavi, P., & Narasimhan, K. (2024). *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains.* arXiv:2406.12045.
- Yu, T., et al. (2018). *Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task.* EMNLP 2018. arXiv:1809.08887.
