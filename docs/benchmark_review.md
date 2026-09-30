# Benchmark review sheet

For each question: run the Cypher in Neo4j Browser, check that the query really answers the question and the result matches. Record ok=1/0 and a comment in `data/review_log.csv`.

## L03 (lookup, easy)

**Q:** What type of device is D-0024?

```cypher
MATCH (d:Device {id: 'D-0024'}) RETURN d.device_type
```

**gold_result** (`set`): `["agg_switch"]`

## L06 (lookup, easy)

**Q:** Which customer segment does customer C-0020 belong to?

```cypher
MATCH (c:Customer {id: 'C-0020'}) RETURN c.segment
```

**gold_result** (`set`): `["business"]`

## L09 (lookup, medium)

**Q:** In which city is the Kerkstraat site located?

```cypher
MATCH (s:Site {name: 'Kerkstraat'}) RETURN DISTINCT s.city
```

**gold_result** (`set`): `["Amsterdam", "Eindhoven"]`

Alternative reading:
```cypher
MATCH (s:Site {name: 'Kerkstraat', city: 'Amsterdam'}) RETURN s.city
```
→ `["Amsterdam"]`

Alternative reading:
```cypher
MATCH (s:Site {name: 'Kerkstraat', city: 'Eindhoven'}) RETURN s.city
```
→ `["Eindhoven"]`

_Notes: Ambiguous - two sites are called Kerkstraat._

## L10 (lookup, medium)

**Q:** Which types of energy source power the Stationsplein site?

```cypher
MATCH (e:EnergySource)-[:POWERS]->(:Site {name: 'Stationsplein'}) RETURN DISTINCT e.source_type
```

**gold_result** (`set`): `["battery", "grid"]`

Alternative reading:
```cypher
MATCH (e:EnergySource)-[:POWERS]->(:Site {name: 'Stationsplein', city: 'Utrecht'}) RETURN DISTINCT e.source_type
```
→ `["grid"]`

Alternative reading:
```cypher
MATCH (e:EnergySource)-[:POWERS]->(:Site {name: 'Stationsplein', city: 'Groningen'}) RETURN DISTINCT e.source_type
```
→ `["battery", "grid"]`

_Notes: Ambiguous - Stationsplein exists in Utrecht and Groningen; only Groningen has a battery._

## F02 (filter_agg, medium)

**Q:** How many OLTs are currently in maintenance in Utrecht?

```cypher
MATCH (:Site {city: 'Utrecht'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (d:Device {device_type: 'olt', status: 'maintenance'}) RETURN count(d)
```

**gold_result** (`number`): `1`

_Notes: City is a Site property, so the query must go Site -> Cabinet -> Device._

## F04 (filter_agg, medium)

**Q:** What is the total length in metres of all copper cables?

```cypher
MATCH (c:Cable {medium: 'copper'}) RETURN sum(c.length_m)
```

**gold_result** (`number`): `13136`

## F08 (filter_agg, hard)

**Q:** List the IDs of the three longest fiber cables, longest first.

```cypher
MATCH (c:Cable {medium: 'fiber'}) RETURN c.id ORDER BY c.length_m DESC LIMIT 3
```

**gold_result** (`list`): `["L-0031", "L-0026", "L-0014"]`

## F10 (filter_agg, medium)

**Q:** Which vendors made the OLTs at the Stationsplein site?

```cypher
MATCH (:Site {name: 'Stationsplein'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (d:Device {device_type: 'olt'}) RETURN DISTINCT d.vendor
```

**gold_result** (`set`): `["Huawei", "Nokia", "ZTE"]`

Alternative reading:
```cypher
MATCH (:Site {name: 'Stationsplein', city: 'Utrecht'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (d:Device {device_type: 'olt'}) RETURN DISTINCT d.vendor
```
→ `["Nokia", "ZTE"]`

Alternative reading:
```cypher
MATCH (:Site {name: 'Stationsplein', city: 'Groningen'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (d:Device {device_type: 'olt'}) RETURN DISTINCT d.vendor
```
→ `["Huawei", "ZTE"]`

_Notes: Ambiguous - Stationsplein exists in Utrecht and Groningen._

## M04 (multi_hop, hard)

**Q:** Which types of energy source power the site that houses device D-0033?

```cypher
MATCH (e:EnergySource)-[:POWERS]->(:Site)-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (:Device {id: 'D-0033'}) RETURN DISTINCT e.source_type
```

**gold_result** (`set`): `["battery", "grid"]`

## M05 (multi_hop, hard)

**Q:** In which city is the site that houses the OLT serving customer C-0020?

```cypher
MATCH (:Customer {id: 'C-0020'})-[:SUBSCRIBES_TO]->(:Service)<-[:DELIVERS]-(ont:Device) <-[:FEEDS]-(olt:Device {device_type: 'olt'})<-[:HOUSES]-(:Cabinet)<-[:CONTAINS]-(s:Site) RETURN DISTINCT s.city
```

**gold_result** (`set`): `["Rotterdam"]`

_Notes: ONTs are not housed in cabinets; the site must be found via the OLT._

## M07 (multi_hop, medium)

**Q:** What is the medium of the cable connecting ONT D-0043 to its OLT?

```cypher
MATCH (olt:Device)-[:FEEDS]->(ont:Device {id: 'D-0043'}) MATCH (olt)<-[:CONNECTS]-(c:Cable)-[:CONNECTS]->(ont) RETURN c.medium
```

**gold_result** (`set`): `["copper"]`

## M09 (multi_hop, hard)

**Q:** At which datacenter site is the core router located that is upstream of OLT D-0034?

```cypher
MATCH (r:Device {device_type: 'core_router'})-[:FEEDS*]->(:Device {id: 'D-0034'}) MATCH (s:Site)-[:CONTAINS]->(:Cabinet)-[:HOUSES]->(r) RETURN s.name
```

**gold_result** (`set`): `["Rotterdam DC"]`

## M10 (multi_hop, hard)

**Q:** Which vendors made the aggregation switches that feed the OLTs at the Kerkstraat site?

```cypher
MATCH (:Site {name: 'Kerkstraat'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (:Device {device_type: 'olt'})<-[:FEEDS]-(a:Device {device_type: 'agg_switch'}) RETURN DISTINCT a.vendor
```

**gold_result** (`set`): `["Cisco", "Nokia"]`

Alternative reading:
```cypher
MATCH (:Site {name: 'Kerkstraat', city: 'Amsterdam'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (:Device {device_type: 'olt'})<-[:FEEDS]-(a:Device {device_type: 'agg_switch'}) RETURN DISTINCT a.vendor
```
→ `["Cisco", "Nokia"]`

Alternative reading:
```cypher
MATCH (:Site {name: 'Kerkstraat', city: 'Eindhoven'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (:Device {device_type: 'olt'})<-[:FEEDS]-(a:Device {device_type: 'agg_switch'}) RETURN DISTINCT a.vendor
```
→ `["Cisco"]`

_Notes: Ambiguous - Kerkstraat exists in Amsterdam and Eindhoven._

## I01 (impact, medium)

**Q:** If aggregation switch D-0029 fails, how many business customers lose service?

```cypher
MATCH (:Device {id: 'D-0029'})-[:FEEDS*]->(:Device)-[:DELIVERS]->(:Service) <-[:SUBSCRIBES_TO]-(c:Customer {segment: 'business'}) RETURN count(DISTINCT c)
```

**gold_result** (`number`): `4`

## I05 (impact, hard)

**Q:** Taking backup batteries into account, how many customers lose service if the grid supply to the Strijp site fails?

```cypher
MATCH (s:Site {name: 'Strijp'}) WHERE NOT EXISTS { (:EnergySource {source_type: 'battery'})-[:POWERS]->(s) } MATCH (s)-[:CONTAINS]->(:Cabinet)-[:HOUSES]->(:Device)-[:FEEDS*]->(:Device)
  -[:DELIVERS]->(:Service)<-[:SUBSCRIBES_TO]-(c:Customer)
RETURN count(DISTINCT c)
```

**gold_result** (`number`): `0`

_Notes: Strijp has a backup battery, so the correct answer is 0._

## I07 (impact, hard)

**Q:** In which cities would customers lose service if core router D-0003 failed?

```cypher
MATCH (:Device {id: 'D-0003'})-[:FEEDS*]->(olt:Device {device_type: 'olt'}) MATCH (s:Site)-[:CONTAINS]->(:Cabinet)-[:HOUSES]->(olt) WHERE EXISTS { (olt)-[:FEEDS]->(:Device)-[:DELIVERS]->(:Service)<-[:SUBSCRIBES_TO]-(:Customer) } RETURN DISTINCT s.city
```

**gold_result** (`set`): `["Den Haag", "Eindhoven", "Rotterdam"]`

## I08 (impact, hard)

**Q:** How many customers are currently without service because their ONT, or any device upstream of it, is in the failed state?

```cypher
MATCH (x:Device {status: 'failed'})-[:FEEDS*0..]->(o:Device {device_type: 'ont'}) MATCH (o)-[:DELIVERS]->(:Service)<-[:SUBSCRIBES_TO]-(c:Customer) RETURN count(DISTINCT c)
```

**gold_result** (`number`): `3`

## I10 (impact, hard)

**Q:** Which customers lose service if the Marktplein site loses all power?

```cypher
MATCH (:Site {name: 'Marktplein'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]->(:Device)-[:FEEDS*]-> (:Device)-[:DELIVERS]->(:Service)<-[:SUBSCRIBES_TO]-(c:Customer) RETURN DISTINCT c.id
```

**gold_result** (`set`): `["C-0016", "C-0017", "C-0018", "C-0019", "C-0020", "C-0021", "C-0022", "C-0023", "C-0024", "C-0025", "C-0053", "C-0054", "C-0055", "C-0056", "C-0057", "C-0058", "C-0059", "C-0060"]`

Alternative reading:
```cypher
MATCH (:Site {name: 'Marktplein', city: 'Rotterdam'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (:Device)-[:FEEDS*]->(:Device)-[:DELIVERS]->(:Service)<-[:SUBSCRIBES_TO]-(c:Customer) RETURN DISTINCT c.id
```
→ `["C-0016", "C-0017", "C-0018", "C-0019", "C-0020", "C-0021", "C-0022", "C-0023", "C-0024", "C-0025"]`

Alternative reading:
```cypher
MATCH (:Site {name: 'Marktplein', city: 'Den Haag'})-[:CONTAINS]->(:Cabinet)-[:HOUSES]-> (:Device)-[:FEEDS*]->(:Device)-[:DELIVERS]->(:Service)<-[:SUBSCRIBES_TO]-(c:Customer) RETURN DISTINCT c.id
```
→ `["C-0053", "C-0054", "C-0055", "C-0056", "C-0057", "C-0058", "C-0059", "C-0060"]`

_Notes: Ambiguous - Marktplein exists in Rotterdam and Den Haag._

## U06 (unanswerable, medium)

**Q:** When did device D-0064 fail?

**gold_result** (`refuse`): `null`

_Notes: D-0064 is failed, but there is no failure timestamp. Saying "it is failed, date unknown" is correct._

## U08 (unanswerable, medium)

**Q:** Who manufactured cable L-0031?

**gold_result** (`refuse`): `null`

_Notes: Devices have a vendor, cables do not - tempting to answer with a device vendor._
