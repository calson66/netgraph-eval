"""Generate the synthetic fixed-network graph and load it into Neo4j.

`generate(seed)` is pure Python (no database) and returns
  {"nodes": {label: [props, ...]}, "rels": [(src_label, type, dst_label, [(src_id, dst_id)])]}.
Same seed -> identical graph. Topology is a tree: core_router -> agg_switch -> olt -> ont.
`build(driver, seed)` wipes the database and loads the generated graph.
Everything is invented; city names are only used to make questions readable.
"""

import random

SEED = 42

# city -> (area code, street-site names). Three names appear in two cities on purpose,
# so that some benchmark questions are ambiguous ("Stationsplein" exists in Utrecht and Groningen).
CITIES = {
    "Amsterdam": ("020", ["Kerkstraat", "Damrak"]),
    "Rotterdam": ("010", ["Marktplein", "Coolsingel"]),
    "Utrecht": ("030", ["Stationsplein", "Oudegracht"]),
    "Den Haag": ("070", ["Marktplein", "Spui"]),
    "Eindhoven": ("040", ["Kerkstraat", "Strijp"]),
    "Groningen": ("050", ["Stationsplein", "Vismarkt"]),
}
# Each city's aggregation layer hangs off the core routers of one datacenter.
DATACENTER_FOR = {
    "Amsterdam": "Amsterdam", "Utrecht": "Amsterdam", "Groningen": "Amsterdam",
    "Rotterdam": "Rotterdam", "Den Haag": "Rotterdam", "Eindhoven": "Rotterdam",
}
VENDORS = {
    "core_router": ["Cisco", "Juniper", "Nokia"],
    "agg_switch": ["Nokia", "Huawei", "Cisco"],
    "olt": ["Nokia", "Huawei", "ZTE"],
    "ont": ["Nokia", "Huawei", "Zyxel"],
}
CABLE_LENGTH_M = {  # by the device type at the lower end of the link
    "agg_switch": (2000, 40000),
    "olt": (500, 8000),
    "ont": (50, 1500),
}
NON_ACTIVE_SHARE = 0.05   # devices in maintenance or failed
BATTERY_SITES = 4         # sites (non-datacenter) with a backup battery
COPPER_SHARE = 0.15       # share of olt->ont links that are legacy copper


def generate(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    nodes = {label: [] for label in
             ["EnergySource", "Site", "Cabinet", "Cable", "Device", "Service", "Customer"]}
    rels: dict[tuple[str, str, str], list[tuple[str, str]]] = {}

    def add_rel(src_label, rel_type, dst_label, src_id, dst_id):
        rels.setdefault((src_label, rel_type, dst_label), []).append((src_id, dst_id))

    def new_id(label, prefix, width):
        return f"{prefix}-{len(nodes[label]) + 1:0{width}d}"

    def add_site(name, city, site_type):
        site = {"id": new_id("Site", "S", 3), "name": name, "city": city, "site_type": site_type}
        nodes["Site"].append(site)
        return site

    def add_cabinet(site, cabinet_type):
        cab = {"id": new_id("Cabinet", "K", 3), "cabinet_type": cabinet_type}
        nodes["Cabinet"].append(cab)
        add_rel("Site", "CONTAINS", "Cabinet", site["id"], cab["id"])
        return cab

    def add_device(device_type, cabinet=None, parent=None):
        dev = {"id": new_id("Device", "D", 4), "device_type": device_type,
               "vendor": rng.choice(VENDORS[device_type]), "status": "active",
               "install_year": rng.randint(2008, 2024)}
        nodes["Device"].append(dev)
        if cabinet:
            add_rel("Cabinet", "HOUSES", "Device", cabinet["id"], dev["id"])
        if parent:
            add_rel("Device", "FEEDS", "Device", parent["id"], dev["id"])
            add_cable(parent, dev)
        return dev

    def add_cable(upper, lower):
        low, high = CABLE_LENGTH_M[lower["device_type"]]
        copper = lower["device_type"] == "ont" and rng.random() < COPPER_SHARE
        cable = {"id": new_id("Cable", "L", 4), "medium": "copper" if copper else "fiber",
                 "length_m": rng.randint(low, high),
                 "install_year": max(upper["install_year"], lower["install_year"])}
        nodes["Cable"].append(cable)
        add_rel("Cable", "CONNECTS", "Device", cable["id"], upper["id"])
        add_rel("Cable", "CONNECTS", "Device", cable["id"], lower["id"])

    # --- sites, cabinets, devices (top-down so every parent exists before its children) ---
    core_by_dc = {}
    for city in ["Amsterdam", "Rotterdam"]:
        dc = add_site(f"{city} DC", city, "datacenter")
        cabs = [add_cabinet(dc, "indoor_rack") for _ in range(2)]
        core_by_dc[city] = [add_device("core_router", cab) for cab in cabs]

    olts_with_city = []
    for city, (_, street_names) in CITIES.items():
        co = add_site(f"{city} Central", city, "central_office")
        cabs = [add_cabinet(co, "indoor_rack") for _ in range(2)]
        aggs = [add_device("agg_switch", cab, rng.choice(core_by_dc[DATACENTER_FOR[city]]))
                for cab in cabs]
        for street in street_names:
            site = add_site(street, city, "street_site")
            cab = add_cabinet(site, "street_cabinet")
            for _ in range(2):
                olts_with_city.append((add_device("olt", cab, rng.choice(aggs)), city))

    # --- ONTs at customer premises (not in a cabinet), one customer each ---
    for olt, city in olts_with_city:
        for _ in range(rng.randint(3, 5)):
            ont = add_device("ont", parent=olt)
            business = rng.random() < 0.2
            cust = {"id": new_id("Customer", "C", 4),
                    "segment": "business" if business else "consumer",
                    "area_code": CITIES[city][0]}
            nodes["Customer"].append(cust)
            if business:
                types = ["business_vpn"] + (["internet"] if rng.random() < 0.5 else [])
            else:
                types = ["internet"] + (["tv"] if rng.random() < 0.4 else [])
            for service_type in types:
                svc = {"id": new_id("Service", "V", 4), "service_type": service_type}
                nodes["Service"].append(svc)
                add_rel("Device", "DELIVERS", "Service", ont["id"], svc["id"])
                add_rel("Customer", "SUBSCRIBES_TO", "Service", cust["id"], svc["id"])

    # --- a few devices not active: roughly half in maintenance, half failed ---
    n_bad = round(NON_ACTIVE_SHARE * len(nodes["Device"]))
    for i, dev in enumerate(rng.sample(nodes["Device"], n_bad)):
        dev["status"] = "maintenance" if i % 2 == 0 else "failed"

    # --- energy: every site on the grid, datacenters get a generator, a few sites a battery ---
    grid_kw = {"datacenter": 2000, "central_office": 500, "street_site": 50}

    def add_energy(site, source_type, capacity_kw):
        src = {"id": new_id("EnergySource", "E", 3), "source_type": source_type,
               "capacity_kw": capacity_kw}
        nodes["EnergySource"].append(src)
        add_rel("EnergySource", "POWERS", "Site", src["id"], site["id"])

    for site in nodes["Site"]:
        add_energy(site, "grid", grid_kw[site["site_type"]])
        if site["site_type"] == "datacenter":
            add_energy(site, "generator", 1500)
    non_dc = [s for s in nodes["Site"] if s["site_type"] != "datacenter"]
    for site in rng.sample(non_dc, BATTERY_SITES):
        add_energy(site, "battery", rng.choice([20, 50, 100]))

    return {"nodes": nodes,
            "rels": [(s, t, d, pairs) for (s, t, d), pairs in rels.items()]}


def build(driver, seed: int = SEED) -> None:
    """Wipe the database, create unique-id constraints, then load nodes and relationships."""
    graph = generate(seed)
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n").consume()
        for label in graph["nodes"]:
            session.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                        f"FOR (n:{label}) REQUIRE n.id IS UNIQUE").consume()
        for label, rows in graph["nodes"].items():
            session.run(f"UNWIND $rows AS row CREATE (n:{label}) SET n = row", rows=rows).consume()
        for src, rel_type, dst, pairs in graph["rels"]:
            session.run(
                f"UNWIND $pairs AS p "
                f"MATCH (a:{src} {{id: p[0]}}) MATCH (b:{dst} {{id: p[1]}}) "
                f"CREATE (a)-[:{rel_type}]->(b)",
                pairs=[list(p) for p in pairs],
            ).consume()
