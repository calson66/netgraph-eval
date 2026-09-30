"""Phase 2 tests: benchmark.jsonl is complete and consistent (no database needed)."""

from collections import Counter

from netgraph.benchmark import load_benchmark


def test_fifty_questions_ten_per_category():
    qs = load_benchmark()
    assert len(qs) == 50
    assert len({q.qid for q in qs}) == 50
    assert set(Counter(q.category for q in qs).values()) == {10}


def test_gold_results_present():
    for q in load_benchmark():
        if q.answer_rule == "refuse":
            assert q.gold_result is None and q.gold_cypher is None, q.qid
        elif q.answer_rule == "number":
            assert isinstance(q.gold_result, int | float), q.qid
        else:
            assert isinstance(q.gold_result, list) and q.gold_result, q.qid


def test_ambiguous_questions_have_distinct_readings():
    amb = [q for q in load_benchmark() if q.ambiguous]
    assert 4 <= len(amb) <= 6
    for q in amb:
        assert len(q.alt_results) == len(q.alt_cyphers) >= 2, q.qid
        assert all(r for r in q.alt_results), q.qid  # every reading has an answer
