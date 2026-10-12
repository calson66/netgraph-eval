# Metric taxonomy for tool-using LLM agents

One page, three layers. For each metric: what it measures, whether it needs a gold answer
(**gold**), whether it can be computed on live traffic (**online**), and where it is implemented
in this project (**here**). "—" means not implemented.

## Outcome layer — did the user get a correct answer?

| Metric | Definition | Gold? | Online? | Here |
|---|---|---|---|---|
| Answer accuracy | Final answer equals the gold answer under the question's rule (set / list / number / refuse) | yes | no | `grading.answer_correct` |
| Execution accuracy | The last successful query's result contains the gold answer (compares results, not query strings — cf. Spider, Yu et al. 2018) | yes | no | `grading.rows_match` → `exec_correct` |
| Refusal correctness | Says "not in the data" exactly when the data cannot answer | yes | no | `answer_rule: refuse` |
| pass^k | Share of questions answered correctly in all k repeats (reliability; τ-bench, Yao et al. 2024) | yes | no | `analysis.pass_all_repeats` |
| Faithfulness | Answer is supported by the query result (LLM judge) | no | yes | `judge.py` |
| Human correctness / usefulness | 0–2 ratings by a reviewer | (human) | sampled | `data/human_ratings.csv` |

## Trajectory layer — how did the agent get there?

| Metric | Definition | Gold? | Online? | Here |
|---|---|---|---|---|
| Schema validity | Query uses only labels / relationships / properties that exist | no | yes | `grading.schema_valid` |
| Schema overlap | Jaccard similarity of schema elements with the gold query | yes | no | `schema_overlap` |
| Syntax validity | Query compiles (no syntax error at run time) | no | yes | `syntax_valid` |
| Query error rate | Share of executed queries that returned an error | no | yes | `analysis.signals` |
| Empty-result rate | Share of successful queries that returned 0 rows | no | yes | `analysis.signals` |
| Steps / queries per run | LLM calls and `run_cypher` calls per question | no | yes | `n_llm_calls`, `n_queries` |
| Repeated query | The same query text run twice in one trajectory | no | yes | `repeated_query` |
| Limit hit | Run stopped by the step or query limit | no | yes | `hit_limit` |
| Recovery | An error / empty result followed by a correct final query | yes | partly | — (visible in traces, not aggregated) |
| Failure stage | First failing stage: schema grounding → trajectory → query generation → answer synthesis (heuristic) | yes | no | `grading.attribute_failure` |

## System layer — what does it cost and is it worth it?

| Metric | Definition | Gold? | Online? | Here |
|---|---|---|---|---|
| Tokens, latency, cost per run | From API usage and a price snapshot | no | yes | `trace.usage`, `configs/pricing.yaml` |
| Cost / tokens per success | Total cost ÷ correct answers (Kapoor et al. 2024: report cost with accuracy) | yes | no | `analysis.value_row` |
| Net value (minutes) | Assumed analyst minutes saved by correct answers − 0.5 × minutes of unescalated wrong answers | yes | no | `configs/value_minutes.yaml` |
| Value per 1k tokens | Net value ÷ (tokens / 1000) | yes | no | `value_row` |
| Escalation rate | Share of runs handed to a human by label-free rules (error, empty, limit, unfaithful) | no | yes | `analysis.escalate` |
| Escalation precision / recall | Of escalated runs, how many were wrong; of wrong runs, how many were escalated | yes | no | `value_row` |
| Drift alarm | A label-free signal leaves the normal band (mean ± 2·SD of repeats) | no | yes | `analysis.degradation_table` |

## References (checked)

- Yao et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023. arXiv:2210.03629
- Yao et al. (2024). *τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains.* arXiv:2406.12045
- Kapoor et al. (2024). *AI Agents That Matter.* arXiv:2407.01502
- Yu et al. (2018). *Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task.* EMNLP 2018. arXiv:1809.08887
- Ozsoy et al. (2024). *Text2Cypher: Bridging Natural Language and Graph Databases.* arXiv:2412.10064
