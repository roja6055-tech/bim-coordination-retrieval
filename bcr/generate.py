"""Generate the synthetic BIM coordination benchmark (version 1.0).

All records are fictional. No real project, owner or issue data are used.
Run:  python -m bcr.generate --out data --seed 20261112
"""
import argparse, json, os, random

GRID_COLS = "ABCDEFGHJK"

def neighbour(zone, rng):
    col, row = zone.split("-")
    i = GRID_COLS.index(col)
    if rng.random() < 0.5:
        i = max(0, min(len(GRID_COLS) - 1, i + rng.choice([-1, 1])))
        return f"{GRID_COLS[i]}-{row}"
    r = max(1, min(9, int(row) + rng.choice([-1, 1])))
    return f"{col}-{r}"

def random_zone(rng):
    return f"{rng.choice(GRID_COLS)}-{rng.randint(1, 9)}"

# Each scenario: a recurring coordination problem with one root cause and one standard resolution.
# Scenarios sharing a "family" use the same symptom wording but have different causes and context:
# these pairs create the hard negatives.
SCENARIOS = [
  dict(id="S01", family="tray_duct", disc=("Electrical", "Mechanical"), elems=["Cable Tray", "Duct"], clash="hard",
       zone="C-4", level="L1", bod="DH-A", phase="IFC",
       causes=["busway route moved after the electrical room layout was mirrored", "electrical room mirrored, pushing the busway and tray into the duct zone"],
       fixes=["lowered the cable tray 300 mm and offset the busway per the revised electrical layout", "dropped tray by 300 mm and shifted busway along the revised route"]),
  dict(id="S02", family="tray_duct", disc=("Architectural", "Mechanical"), elems=["Cable Tray", "Duct", "Ceiling"], clash="hard",
       zone="D-4", level="L1", bod="DH-A", phase="DD",
       causes=["office ceiling raised, squeezing the services zone above it", "raised ceiling height in the office wing reduced plenum depth"],
       fixes=["rerouted the duct above the corridor and kept the tray at its original elevation", "moved duct over corridor; tray unchanged"]),
  dict(id="S03", family="pipe_beam", disc=("Mechanical", "Structural"), elems=["Pipe", "Structural Framing"], clash="hard",
       zone="H-2", level="L1", bod="CUP", phase="IFC",
       causes=["chilled water main upsized in a later design revision", "larger chilled water header after load update"],
       fixes=["relocated the chilled water pipe below the beam and added a hanger detail", "ran CHW main under the beam with new hanger detail"]),
  dict(id="S04", family="pipe_beam", disc=("Fire Protection", "Structural"), elems=["Sprinkler Pipe", "Structural Framing"], clash="hard",
       zone="H-3", level="L1", bod="CUP", phase="DD",
       causes=["beam depth increased to carry heavier rooftop units", "deeper roof beams for added rooftop equipment load"],
       fixes=["dropped the sprinkler branch below the beam and adjusted head spacing", "lowered branch line and re-spaced heads"]),
  dict(id="S05", family="containment", disc=("Architectural", "Electrical"), elems=["Hot Aisle Containment", "Lighting Fixture"], clash="clearance",
       zone="E-3", level="L1", bod="DH-A", phase="IFC",
       causes=["containment roof height changed in the current design standard", "taller containment roof in the latest standard"],
       fixes=["moved light fixtures onto the containment frame", "mounted fixtures on containment frame instead of ceiling"]),
  dict(id="S06", family="containment", disc=("Architectural", "Fire Protection"), elems=["Hot Aisle Containment", "Sprinkler Head"], clash="clearance",
       zone="E-4", level="L1", bod="DH-A", phase="DD",
       causes=["sprinkler heads above the containment roof are obstructed", "containment roof blocks sprinkler spray pattern"],
       fixes=["added sprinkler heads inside the containment per the fire engineer", "fire engineer approved heads inside containment"]),
  dict(id="S07", family=None, disc=("Mechanical", "Structural"), elems=["Generator Exhaust", "Structural Framing"], clash="hard",
       zone="J-1", level="Roof", bod="CUP", phase="IFC",
       causes=["generator exhaust stack moved to meet setback rules"], fixes=["added roof framing opening and trimmer beams for the exhaust"]),
  dict(id="S08", family=None, disc=("Electrical", "Mechanical"), elems=["Busway", "Duct Accessory"], clash="clearance",
       zone="B-5", level="L2", bod="DH-A", phase="IFC",
       causes=["busway blocks access to the fire damper"], fixes=["shifted busway 450 mm to keep damper access panel clear"]),
  dict(id="S09", family=None, disc=("Mechanical", "Architectural"), elems=["Pipe", "Floor"], clash="hard",
       zone="G-4", level="L1", bod="DH-B", phase="Construction",
       causes=["cooling unit condensate line routed through raised-floor pedestals"], fixes=["rerouted condensate line between pedestal rows"]),
  dict(id="S10", family=None, disc=("Electrical", "Architectural"), elems=["Conduit", "Door"], clash="clearance",
       zone="A-2", level="L1", bod="ADMIN", phase="DD",
       causes=["surface conduit placed in the door swing zone"], fixes=["moved conduit into the wall above the door head"]),
  dict(id="S11", family=None, disc=("Electrical", "Fire Protection"), elems=["Cable Tray", "Sprinkler Pipe"], clash="hard",
       zone="C-8", level="L1", bod="DH-A", phase="IFC",
       causes=["cable ladder and sprinkler main share one elevation band"], fixes=["assigned separate elevation bands to tray and sprinkler main"]),
  dict(id="S12", family=None, disc=("Mechanical", "Plumbing"), elems=["Mechanical Equipment", "Pipe"], clash="hard",
       zone="K-6", level="Roof", bod="CUP", phase="IFC",
       causes=["rooftop unit placed over a roof drain"], fixes=["moved roof drain and regraded roof insulation"]),
]

SYMPTOMS = {
  "tray_duct": ["cable tray clashes with supply duct near grid {z}", "tray runs into the duct main at {z}",
                "conflict between cable tray and ductwork at {z}", "cable tray and duct collide around {z}",
                "ductwork hits the cable tray at {z}"],
  "pipe_beam": ["pipe hits steel beam at {z}", "pipe clashes with structural beam near {z}",
                "piping runs through the beam at {z}", "beam and pipe conflict around {z}", "pipe collides with framing at {z}"],
  "containment": ["containment clashes with overhead services at {z}", "overhead items conflict with aisle containment at {z}",
                  "containment roof hits items above at {z}", "clearance problem over hot aisle containment at {z}",
                  "services above containment are too low at {z}"],
  "S07": ["generator exhaust clashes with roof framing at {z}", "exhaust stack hits roof steel at {z}", "genset flue conflicts with beams at {z}"],
  "S08": ["busway blocks fire damper access at {z}", "no access to damper because of busduct at {z}", "busduct in front of damper at {z}"],
  "S09": ["condensate pipe clashes with floor pedestals at {z}", "drain line runs through raised floor supports at {z}", "pedestals hit condensate line at {z}"],
  "S10": ["conduit inside door swing at {z}", "door hits surface conduit at {z}", "conduit clashes with door at {z}"],
  "S11": ["cable ladder clashes with sprinkler main at {z}", "sprinkler main runs into cable ladder at {z}", "tray and sprinkler main collide at {z}"],
  "S12": ["rooftop unit sits on roof drain at {z}", "roof drain under mechanical unit at {z}", "RTU clashes with drain at {z}"],
}

NOVEL = [
  dict(text="battery rack clashes with structural column at {z}", disc=("Electrical", "Structural"), elems=["Electrical Equipment", "Structural Column"], clash="hard", zone="B-9", level="L1", bod="DH-A", phase="IFC"),
  dict(text="fuel line crosses cable trench at {z}", disc=("Mechanical", "Electrical"), elems=["Pipe", "Cable Trench"], clash="hard", zone="J-8", level="L1", bod="CUP", phase="DD"),
  dict(text="louver blocked by conduit bank at {z}", disc=("Architectural", "Electrical"), elems=["Louver", "Conduit"], clash="clearance", zone="A-7", level="L2", bod="ADMIN", phase="IFC"),
  dict(text="eyewash station clashes with pipe riser at {z}", disc=("Plumbing", "Mechanical"), elems=["Plumbing Fixture", "Pipe"], clash="hard", zone="K-2", level="L1", bod="CUP", phase="Construction"),
]

UNRELATED_TOPICS = [
  ("Architectural", "Structural", ["Wall", "Structural Column"], "wall misaligned with column at {z}", "updated wall layout", "wall offset from column grid"),
  ("Mechanical", "Electrical", ["Duct", "Electrical Equipment"], "duct above switchboard at {z}", "rerouted duct away from switchboard", "duct over electrical equipment not allowed"),
  ("Plumbing", "Architectural", ["Pipe", "Ceiling"], "drain pipe below ceiling at {z}", "raised drain into plenum", "pipe slope not modeled"),
  ("Fire Protection", "Mechanical", ["Sprinkler Pipe", "Duct"], "sprinkler branch crosses duct at {z}", "swapped elevations", "branch routed late"),
  ("Electrical", "Structural", ["Conduit", "Structural Framing"], "conduit penetrates beam web at {z}", "rerouted conduit below beam", "penetration not approved"),
  ("Architectural", "Mechanical", ["Door", "Mechanical Equipment"], "unit blocks door access at {z}", "moved unit 600 mm", "maintenance clearance missed"),
  ("Mechanical", "Structural", ["Duct", "Structural Column"], "duct clashes with column at {z}", "split duct around column", "column enlarged"),
  ("Electrical", "Mechanical", ["Lighting Fixture", "Air Terminal"], "light fixture overlaps diffuser at {z}", "shifted fixture", "reflected ceiling plan updated"),
]

def para(text, rng):
    swaps = {"clashes with": ["clashes with", "conflicts with", "hits", "runs into"],
             "near": ["near", "around", "at"], "conflict": ["conflict", "clash", "collision"]}
    for k, v in swaps.items():
        if k in text and rng.random() < 0.6:
            text = text.replace(k, rng.choice(v), 1)
    return text

def make_record(rid, sc, rng, superseded, bod_version):
    z = sc["zone"]
    disc = list(sc["disc"])
    zone = z
    if rng.random() < 0.35:
        zone = neighbour(z, rng) if rng.random() < 0.7 else random_zone(rng)
    if rng.random() < 0.15:
        disc = disc[::-1] if rng.random() < 0.5 else [disc[0]]
    elems = list(sc["elems"])
    if rng.random() < 0.20:
        elems = elems[:-1] + ["Generic Model"] if rng.random() < 0.5 else elems[:1]
    phase = sc["phase"] if rng.random() >= 0.30 else rng.choice(["DD", "IFC", "Construction"])
    level = sc["level"] if rng.random() >= 0.15 else rng.choice(["L1", "L2", "Roof"])
    sym_pool = SYMPTOMS[sc["family"] or sc["id"]]
    cause = rng.choice(sc["causes"]) if rng.random() >= 0.35 else ""
    return dict(record_id=rid, scenario=sc["id"], project=f"P{rng.randint(1, 9):02d}", phase=phase,
                bod_family=sc["bod"], bod_version=bod_version, grid_zone=zone, level=level,
                discipline_pair=disc, element_categories=elems, clash_type=sc["clash"],
                symptom=para(rng.choice(sym_pool).format(z=zone), rng), root_cause=cause,
                resolution=rng.choice(sc["fixes"]), superseded=superseded,
                superseded_by=None, source_document=f"coordination-log-{rid}.pdf", synthetic=True)

QVOCAB = {"cable tray": ["cable ladder", "tray"], "duct": ["air duct", "ductwork"], "beam": ["girder", "steel member"],
          "pipe": ["line", "piping"], "containment": ["aisle enclosure", "containment"]}

def qvocab(text, rng):
    for k, v in QVOCAB.items():
        if k in text and rng.random() < 0.5:
            text = text.replace(k, rng.choice(v), 1)
    return text

def build(seed):
    rng = random.Random(seed)
    records, n = [], 0
    for sc in SCENARIOS:
        ids = []
        for j in range(14):
            n += 1
            stale = j >= 12
            flagged = j == 12  # j == 13 is stale but nobody recorded it: no flag, current version label
            rec = make_record(f"R{n:03d}", sc, rng, flagged, "v2" if flagged else "v3")
            rec["stale_truth"] = stale
            records.append(rec); ids.append(rec["record_id"])
        records[-2]["superseded_by"] = ids[0]
    for j in range(32):
        n += 1
        d1, d2, el, sym, fix, cause = UNRELATED_TOPICS[j % len(UNRELATED_TOPICS)]
        z = random_zone(rng)
        records.append(dict(record_id=f"R{n:03d}", scenario="UNREL", project=f"P{rng.randint(1, 9):02d}",
                            phase=rng.choice(["DD", "IFC", "Construction"]), bod_family=rng.choice(["DH-A", "DH-B", "ADMIN", "CUP"]),
                            bod_version="v3", grid_zone=z, level=rng.choice(["L1", "L2", "Roof"]), discipline_pair=[d1, d2],
                            element_categories=el, clash_type=rng.choice(["hard", "clearance"]), symptom=para(sym.format(z=z), rng),
                            root_cause=cause if rng.random() >= 0.35 else "", resolution=fix, superseded=False, superseded_by=None,
                            source_document=f"coordination-log-R{n:03d}.pdf", synthetic=True, stale_truth=False))
    rng.shuffle(records)
    # queries: 3 per scenario (36) + 4 novel = 40; split 13 dev / 27 test with 1 novel in dev, 3 in test
    QUERY_TEMPLATES = {"tray_duct": "new issue: tray and supply duct overlap at {z}",
                       "pipe_beam": "new issue: pipe passes through a beam at {z}",
                       "containment": "new issue: items over the hot aisle containment are in the way at {z}"}
    queries = []
    qn = 0
    for sc in SCENARIOS:
        for j in range(3):
            qn += 1
            pool = SYMPTOMS[sc["family"] or sc["id"]]
            base = QUERY_TEMPLATES.get(sc["family"]) if (j == 0 and sc["family"]) else rng.choice(pool)
            qz = sc["zone"] if rng.random() >= 0.40 else neighbour(sc["zone"], rng)
            qel = list(sc["elems"]) if rng.random() >= 0.30 else list(sc["elems"])[:1]
            qph = sc["phase"] if rng.random() >= 0.30 else rng.choice(["DD", "IFC", "Construction"])
            queries.append(dict(query_id=f"Q{qn:02d}", scenario=sc["id"], text=qvocab(para(base.format(z=qz), rng), rng),
                                phase=qph, bod_family=sc["bod"], bod_version="v3", grid_zone=qz, level=sc["level"],
                                discipline_pair=list(sc["disc"]), element_categories=qel, clash_type=sc["clash"]))
    for nv in NOVEL:
        qn += 1
        queries.append(dict(query_id=f"Q{qn:02d}", scenario="NOVEL", text=nv["text"].format(z=nv["zone"]), phase=nv["phase"],
                            bod_family=nv["bod"], bod_version="v3", grid_zone=nv["zone"], level=nv["level"],
                            discipline_pair=list(nv["disc"]), element_categories=list(nv["elems"]), clash_type=nv["clash"]))
    scen_q = [q for q in queries if q["scenario"] != "NOVEL"]
    novel_q = [q for q in queries if q["scenario"] == "NOVEL"]
    dev, test = [], []
    for sc in SCENARIOS:  # one query per scenario to dev, two to test
        qs = [q for q in scen_q if q["scenario"] == sc["id"]]
        dev.append(qs[0]); test.extend(qs[1:])
    dev.append(novel_q[0]); test.extend(novel_q[1:])
    for q in dev: q["split"] = "dev"
    for q in test: q["split"] = "test"
    # graded relevance and hard negatives
    fam = {s["id"]: s["family"] for s in SCENARIOS}
    qrels = []
    for q in dev + test:
        for r in records:
            if q["scenario"] != "NOVEL" and r["scenario"] == q["scenario"]:
                g = 1 if r.get("stale_truth") else 3
                qrels.append(dict(query_id=q["query_id"], record_id=r["record_id"], grade=g, hard_negative=False))
            elif (q["scenario"] != "NOVEL" and r["scenario"] in fam and fam[q["scenario"]] is not None
                  and fam[r["scenario"]] == fam[q["scenario"]] and r["scenario"] != q["scenario"]):
                qrels.append(dict(query_id=q["query_id"], record_id=r["record_id"], grade=0, hard_negative=True))
    return records, dev + test, qrels

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--out", default="data"); ap.add_argument("--seed", type=int, default=20261112)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    recs, qs, qrels = build(a.seed)
    for name, obj in (("records.json", recs), ("queries.json", qs), ("qrels.json", qrels)):
        json.dump(obj, open(os.path.join(a.out, name), "w"), indent=1)
    print(len(recs), "records,", len(qs), "queries,", sum(q["split"] == "test" for q in qs), "test")
