"""Phase 4 tests for grading: answer rules, ambiguity, schema checks, failure attribution."""

from netgraph.benchmark import Question
from netgraph.grading import grade, schema_elements
from netgraph.trace import FinalAnswer, QueryRecord, Trace


def q(rule="set", gold=None, alts=(), cat="lookup", cypher="MATCH (d:Device) RETURN d.vendor"):
    return Question(qid="X", question="?", category=cat, difficulty="easy", answer_rule=rule,
                    gold_cypher=None if rule == "refuse" else cypher, gold_result=gold,
                    alt_cyphers=["a", "b"] if alts else [], alt_results=list(alts))


def t(values=(), cannot=False, queries=(), reason="final"):
    return Trace(run_id="r", qid="X", config="agent", model="m", prompt_version="v",
                 final=FinalAnswer(answer_values=list(values), cannot_answer=cannot),
                 queries=list(queries), terminated_reason=reason)


def rec(query="MATCH (d:Device) RETURN d.vendor", rows=(), status="ok", error_type=None):
    return QueryRecord(query=query, status=status, error_type=error_type, rows=list(rows))


def test_set_rule_ignores_order_and_case():
    assert grade(q(gold=["Nokia", "ZTE"]), t(["zte", "Nokia"]))["answer_correct"]
    assert not grade(q(gold=["Nokia", "ZTE"]), t(["Nokia"]))["answer_correct"]


def test_number_rule_accepts_numeric_strings():
    assert grade(q("number", 4), t(["4"]))["answer_correct"]
    assert not grade(q("number", 4), t([4, 5]))["answer_correct"]


def test_list_rule_needs_order():
    assert not grade(q("list", ["a", "b"]), t(["b", "a"]))["answer_correct"]


def test_ambiguous_accepts_one_reading():
    question = q(gold=["Amsterdam", "Eindhoven"], alts=[["Amsterdam"], ["Eindhoven"]])
    assert grade(question, t(["Eindhoven"]))["answer_correct"]


def test_refuse_rule():
    assert grade(q("refuse", cat="unanswerable"), t(cannot=True))["answer_correct"]
    assert not grade(q("refuse", cat="unanswerable"), t(["42"]))["answer_correct"]


def test_schema_elements():
    used = schema_elements("MATCH (s:Site {name: 'X'})-[:CONTAINS]->(k)-[:HOUSES]->(d:Device) "
                           "WHERE d.status = 'failed' RETURN d.id")
    assert used == {"labels": {"Site", "Device"}, "rels": {"CONTAINS", "HOUSES"},
                    "props": {"name", "status", "id"}}


def test_failure_schema_grounding():
    g = grade(q("refuse", cat="unanswerable"),
              t(["100"], queries=[rec("MATCH (c:Customer) RETURN c.revenue", [{"x": 100}])]))
    assert g["failure_stage"] == "schema_grounding"


def test_failure_query_generation_and_answer_synthesis():
    question = q(gold=["Nokia"])
    wrong_rows = [rec(rows=[{"v": "ZTE"}])]
    assert grade(question, t(["ZTE"], queries=wrong_rows))["failure_stage"] == "query_generation"
    right_rows = [rec(rows=[{"v": "Nokia"}])]
    g = grade(question, t(["Cisco"], queries=right_rows))
    assert g["exec_correct"] and g["failure_stage"] == "answer_synthesis"


def test_failure_trajectory_drift_and_limit():
    question = q(gold=["Nokia"])
    drift = [rec(rows=[{"v": "Nokia"}]), rec(rows=[{"v": "ZTE"}])]
    assert grade(question, t(["ZTE"], queries=drift))["failure_stage"] == "trajectory"
    g = grade(question, t([], queries=[rec(rows=[])], reason="max_steps"))
    assert g["failure_stage"] == "trajectory"
