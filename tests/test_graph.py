"""Phase 1 tests for the synthetic network graph.

- Offline: the generator is deterministic and has the intended structure.
- `neo4j`: rebuild the graph, then 10 fixed Cypher smoke queries must return the expected values.
  Expected values were recorded from seed 42; if graph_gen.py changes, they must be re-checked.
"""

import pytest

from netgraph import db, graph_gen

# (description, query, expected result rows)
SMOKE_QUERIES = [
    ("total nodes",
     "MATCH (n) RETURN count(n) AS n",
     [{"n": 592}]),
    ("devices per type",
     "MATCH (d:Device) RETURN d.device_type AS type, count(*) AS n ORDER BY type",
     [{"type": "agg_switch", "n": 12}, {"type": "core_router", "n": 4},
      {"type": "olt", "n": 24}, {"type": "ont", "n": 98}]),
    ("devices per status",
     "MATCH (d:Device) RETURN d.status AS status, count(*) AS n ORDER BY status",
     [{"status": "active", "n": 131}, {"status": "failed", "n": 3},
      {"status": "maintenance", "n": 4}]),
    ("tree: every non-core device has exactly one parent",
     "MATCH (d:Device) WHERE d.device_type <> 'core_router' "
     "AND COUNT { (:Device)-[:FEEDS]->(d) } <> 1 RETURN count(d) AS bad",
     [{"bad": 0}]),
    ("every ONT is 3 FEEDS hops below a core router",
     "MATCH (o:Device {device_type: 'ont'}) "
     "WHERE NOT EXISTS { (:Device {device_type: 'core_router'})-[:FEEDS*3]->(o) } "
     "RETURN count(o) AS bad",
     [{"bad": 0}]),
    ("every cable connects exactly two devices",
     "MATCH (c:Cable) WHERE COUNT { (c)-[:CONNECTS]->(:Device) } <> 2 RETURN count(c) AS bad",
     [{"bad": 0}]),
    ("ambiguous site names",
     "MATCH (s:Site) WITH s.name AS name, count(*) AS n WHERE n > 1 RETURN name ORDER BY name",
     [{"name": "Kerkstraat"}, {"name": "Marktplein"}, {"name": "Stationsplein"}]),
    ("sites with a backup battery",
     "MATCH (:EnergySource {source_type: 'battery'})-[:POWERS]->(s:Site) "
     "RETURN s.name AS name, s.city AS city ORDER BY name, city",
     [{"name": "Eindhoven Central", "city": "Eindhoven"},
      {"name": "Groningen Central", "city": "Groningen"},
      {"name": "Stationsplein", "city": "Groningen"},
      {"name": "Strijp", "city": "Eindhoven"}]),
    ("OLTs in maintenance in Utrecht",
     "MATCH (s:Site {city: 'Utrecht'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]->"
     "(d:Device {device_type: 'olt', status: 'maintenance'}) RETURN count(d) AS n",
     [{"n": 1}]),
    ("impact: business customers below agg switch D-0029",
     "MATCH (:Device {id: 'D-0029'})-[:FEEDS*]->(:Device)-[:DELIVERS]->(:Service)"
     "<-[:SUBSCRIBES_TO]-(c:Customer {segment: 'business'}) RETURN count(DISTINCT c) AS n",
     [{"n": 4}]),
]


def test_generator_is_deterministic():
    assert graph_gen.generate(42) == graph_gen.generate(42)
    assert graph_gen.generate(42) != graph_gen.generate(7)


def test_generator_size_and_shares():
    g = graph_gen.generate()
    n_nodes = sum(len(rows) for rows in g["nodes"].values())
    assert 400 <= n_nodes <= 800
    devices = g["nodes"]["Device"]
    non_active = [d for d in devices if d["status"] != "active"]
    assert 0.03 <= len(non_active) / len(devices) <= 0.07
    ids = [n["id"] for rows in g["nodes"].values() for n in rows]
    assert len(ids) == len(set(ids))


@pytest.fixture(scope="module")
def driver():
    d = db.get_driver()
    graph_gen.build(d)
    yield d
    d.close()


@pytest.mark.neo4j
@pytest.mark.parametrize("desc,query,expected", SMOKE_QUERIES, ids=[q[0] for q in SMOKE_QUERIES])
def test_smoke_query(driver, desc, query, expected):
    res = db.run_readonly(driver, query)
    assert res["status"] == "ok", res
    assert res["rows"] == expected
