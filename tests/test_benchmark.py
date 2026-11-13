import json, os
D = os.path.join(os.path.dirname(__file__), "..", "data")

def load(n): return json.load(open(os.path.join(D, n)))

def test_counts():
    recs, qs = load("records.json"), load("queries.json")
    assert len(recs) == 200 and len(qs) == 40
    assert sum(q["split"] == "dev" for q in qs) == 13 and sum(q["split"] == "test" for q in qs) == 27
    assert sum(q["scenario"] == "NOVEL" and q["split"] == "test" for q in qs) == 3

def test_all_synthetic():
    assert all(r["synthetic"] for r in load("records.json"))

def test_regenerates_identically():
    from bcr.generate import build
    recs, qs, qrels = build(20261112)
    assert recs == load("records.json") and qs == load("queries.json")
