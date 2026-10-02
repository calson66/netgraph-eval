"""Neo4j access for NetGraph-Eval.

- `get_driver()` reads connection settings from .env.
- `run_readonly()` is what the agent's `run_cypher` tool uses: keyword guard + read transaction,
  5 s timeout, at most 50 rows, and errors returned as a dict instead of raised.
- `get_schema()` reads labels, relationship patterns and properties live from the database.
"""

import os
import re

from dotenv import load_dotenv
from neo4j import Driver, GraphDatabase, unit_of_work
from neo4j.exceptions import ClientError, CypherSyntaxError, Neo4jError

load_dotenv()

TIMEOUT_S = 5
MAX_ROWS = 50
MAX_ENUM_VALUES = 10  # get_schema lists the values of string properties with at most this many

# Neo4j Community has no role-based access control, so we cannot create a real read-only user.
# Instead: (1) reject write keywords here, (2) run everything in a read transaction.
FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH)\b|LOAD\s+CSV|CALL\s+dbms",
    re.IGNORECASE,
)


def get_driver() -> Driver:
    return GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"]),
        notifications_min_severity="OFF",  # silence deprecation warnings from db.schema.*
    )


def is_forbidden(query: str) -> bool:
    # Strip string literals first so e.g. WHERE d.name = 'SET-01' is not rejected.
    no_strings = re.sub(r"'[^']*'|\"[^\"]*\"", "''", query)
    return FORBIDDEN.search(no_strings) is not None


def run_readonly(driver: Driver, query: str) -> dict:
    """Execute a read-only query. Never raises; returns {status, rows, truncated} or an error."""
    if is_forbidden(query):
        return {"status": "error", "error_type": "forbidden",
                "message": "Only read queries are allowed."}

    @unit_of_work(timeout=TIMEOUT_S)
    def _work(tx):
        result = tx.run(query)
        rows = []
        for record in result:
            if len(rows) == MAX_ROWS:
                return rows, True
            rows.append(record.data())
        return rows, False

    try:
        with driver.session() as session:
            rows, truncated = session.execute_read(_work)
        return {"status": "ok", "rows": rows, "truncated": truncated}
    except CypherSyntaxError as e:
        return {"status": "error", "error_type": "syntax", "message": e.message}
    except ClientError as e:
        kind = "timeout" if "Timeout" in (e.code or "") else "client"
        return {"status": "error", "error_type": kind, "message": e.message}
    except Neo4jError as e:
        return {"status": "error", "error_type": "db", "message": str(e)}


def explain_ok(driver: Driver, query: str) -> bool:
    """True if `EXPLAIN <query>` compiles (used for the syntax_valid metric)."""
    try:
        with driver.session() as session:
            session.run("EXPLAIN " + query).consume()
        return True
    except Neo4jError:
        return False


def get_schema(driver: Driver) -> dict:
    """Sorted labels, relationship patterns and properties, read live from the database."""
    with driver.session() as session:
        node_props = session.run(
            "CALL db.schema.nodeTypeProperties() "
            "YIELD nodeLabels, propertyName RETURN nodeLabels, propertyName"
        ).data()
        rel_props = session.run(
            "CALL db.schema.relTypeProperties() "
            "YIELD relType, propertyName RETURN relType, propertyName"
        ).data()
        patterns = session.run(
            "MATCH (a)-[r]->(b) "
            "RETURN DISTINCT labels(a)[0] AS src, type(r) AS rel, labels(b)[0] AS dst"
        ).data()

    nodes: dict[str, set] = {}
    for row in node_props:
        for label in row["nodeLabels"]:
            nodes.setdefault(label, set())
            if row["propertyName"]:
                nodes[label].add(row["propertyName"])

    rels: dict[str, set] = {}
    for row in rel_props:
        rel = row["relType"].strip(":`")
        rels.setdefault(rel, set())
        if row["propertyName"]:
            rels[rel].add(row["propertyName"])

    # For string properties with few distinct values, list the values (e.g. Device.status),
    # so the model does not have to guess spellings like 'olt' vs 'OLT'.
    values = {}
    with driver.session() as session:
        for label, props in sorted(nodes.items()):
            for prop in sorted(props):
                vals = session.run(
                    f"MATCH (n:`{label}`) WHERE n.`{prop}` IS NOT NULL "
                    f"WITH DISTINCT n.`{prop}` AS v LIMIT {MAX_ENUM_VALUES + 1} RETURN collect(v)"
                ).single()[0]
                if len(vals) <= MAX_ENUM_VALUES and all(isinstance(v, str) for v in vals):
                    values[f"{label}.{prop}"] = sorted(vals)

    return {
        "nodes": {k: sorted(v) for k, v in sorted(nodes.items())},
        "relationships": {k: sorted(v) for k, v in sorted(rels.items())},
        "patterns": sorted(f"(:{p['src']})-[:{p['rel']}]->(:{p['dst']})" for p in patterns),
        "values": values,
    }
