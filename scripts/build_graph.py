"""Rebuild the synthetic network graph in Neo4j from scratch.

Steps: wipe database -> unique-id constraints -> load nodes and relationships -> print counts.
Deterministic (fixed seed), so running it twice gives the same graph.
Usage: uv run python scripts/build_graph.py
"""

from netgraph.db import get_driver
from netgraph.graph_gen import build


def print_counts(driver) -> None:
    with driver.session() as session:
        nodes = session.run("MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n "
                            "ORDER BY label").data()
        rels = session.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n "
                           "ORDER BY type").data()
    print("Nodes:", sum(r["n"] for r in nodes))
    for r in nodes:
        print(f"  {r['label']:<14}{r['n']:>5}")
    print("Relationships:", sum(r["n"] for r in rels))
    for r in rels:
        print(f"  {r['type']:<14}{r['n']:>5}")


if __name__ == "__main__":
    driver = get_driver()
    build(driver)
    print_counts(driver)
    driver.close()
