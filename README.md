# bim-coordination-retrieval

An open synthetic benchmark and reference implementation for retrieving resolved BIM coordination
precedents, from the article *Evidence-Grounded Retrieval of Historical BIM Coordination Knowledge:
A Human-in-the-Loop Framework and Open Synthetic Benchmark* (Malligarjunan, 2026).

**All data are synthetic.** No real project, owner, issue log or employer data are used.

## What is in it

| Path | Contents |
|---|---|
| `bcr/generate.py` | Generates the benchmark: 200 issue records, 40 queries, graded relevance labels |
| `bcr/retrieve.py` | BM25, LSA, structured-feature ranker, weighted reciprocal rank fusion, superseded-record demotion, abstention, rule-based answer contract |
| `bcr/evaluate.py` | Tunes on the dev split, reports on the test split, bootstrap intervals, paired tests, robustness and ablation |
| `data/` | `records.json`, `queries.json`, `qrels.json` (version 1.0, seed 20261112) |
| `results/results.json` | Results reported in the article |
| `tests/` | Basic checks of the benchmark's structure |

## Benchmark design (v1.0)

- 12 recurring coordination scenarios with 14 records each, plus 32 unrelated records.
- Three scenario pairs share symptom wording, basis-of-design family and neighbouring grid zones but differ in
  disciplines, elements and root cause: these produce the hard negatives.
- Two stale records per scenario: one recorded as superseded, one whose supersession was never recorded.
- Record noise: 35% no recorded cause, 15% reversed or missing discipline pair, 35% neighbouring or random grid
  zone, 20% incomplete element categories, 30% different phase, 15% different level.
- Query noise: 40% neighbouring grid zone, 30% partial element categories, 30% different phase, and query-only
  vocabulary (for example "cable ladder" for "cable tray").
- 40 queries: 13 dev and 27 test. Four have no precedent (1 dev, 3 test).
- Relevance: current record of the same scenario = 3, stale record of the same scenario = 1, other = 0.

## Reproduce

```bash
pip install -r requirements.txt
python -m bcr.generate --out data --seed 20261112
python -m bcr.evaluate --data data --out results
python -m pytest -q
```

## Licence

Code: MIT. Data: CC BY 4.0. See `LICENSE` and `LICENSE-DATA`.

## Citation

See `CITATION.cff`. Add the Zenodo DOI here after the first release.
