"""Apply or undo the `schema_changed` degradation in the live database.

apply   : rename Device.status -> Device.op_state and relationship FEEDS -> UPLINKS_TO
          (values and topology unchanged, so every gold answer stays the same).
restore : rebuild the original graph from the seed.
Usage: uv run python scripts/schema_change.py apply|restore
"""

import sys

from netgraph.db import get_driver
from netgraph.graph_gen import build

APPLY = [
    "MATCH (d:Device) SET d.op_state = d.status REMOVE d.status",
    "MATCH (a)-[r:FEEDS]->(b) CREATE (a)-[:UPLINKS_TO]->(b) DELETE r",
]


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    driver = get_driver()
    if action == "apply":
        with driver.session() as session:
            for statement in APPLY:
                session.run(statement).consume()
        print("Schema changed: Device.status -> op_state, FEEDS -> UPLINKS_TO")
    elif action == "restore":
        build(driver)
        print("Original graph rebuilt.")
    else:
        sys.exit(__doc__)
    driver.close()


if __name__ == "__main__":
    main()
