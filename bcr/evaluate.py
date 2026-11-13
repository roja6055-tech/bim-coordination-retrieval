"""Tune on dev, report on test. Run: python -m bcr.evaluate --data data --out results"""
import argparse, json, math, os, copy
import numpy as np
from . import retrieve as R

METHODS = [("keyword", "Keyword (BM25)"), ("semantic", "Semantic (LSA)"), ("kw+sem", "Keyword + semantic"),
           ("feature", "Feature only"), ("hybrid", "Hybrid, equal weights"), ("hybrid+demote", "Hybrid + superseded demotion"),
           ("weighted+demote", "Weighted hybrid + demotion")]

def ndcg5(ranked_ids, grades):
    dcg = sum((2 ** grades.get(r, 0) - 1) / math.log2(i + 2) for i, r in enumerate(ranked_ids[:5]))
    ideal = sorted(grades.values(), reverse=True)[:5]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0

def metrics(q, ranked_ids, qrel):
    grades = {r: v["grade"] for r, v in qrel.items() if v["grade"] > 0}
    hard = {r for r, v in qrel.items() if v["hard_negative"]}
    stale = {r for r, v in qrel.items() if v["grade"] == 1}
    rel = {r for r, g in grades.items() if g >= 3}
    rr = next((1 / (i + 1) for i, r in enumerate(ranked_ids) if grades.get(r, 0) >= 3), 0.0)
    return dict(ndcg5=ndcg5(ranked_ids, grades), mrr=rr,
                recall10=len(rel & set(ranked_ids[:10])) / len(rel) if rel else 0.0,
                hard5=len(hard & set(ranked_ids[:5])) / 5, stale5=len(stale & set(ranked_ids[:5])) / 5)

def evaluate(ret, records, queries, qrels, method, w=3.0):
    rows = []
    for q in queries:
        if q["scenario"] == "NOVEL": continue
        idx, _ = ret.run(q, method, w_feat=w)
        rows.append(metrics(q, [records[i]["record_id"] for i in idx], qrels[q["query_id"]]))
    return rows

def mean(rows, k): return float(np.mean([r[k] for r in rows]))

def boot_ci(vals, n=2000, seed=7):
    rng = np.random.default_rng(seed); vals = np.array(vals)
    bs = [rng.choice(vals, len(vals), replace=True).mean() for _ in range(n)]
    return float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--data", default="data"); ap.add_argument("--out", default="results")
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    records = json.load(open(f"{a.data}/records.json")); queries = json.load(open(f"{a.data}/queries.json"))
    qrels = {}
    for x in json.load(open(f"{a.data}/qrels.json")): qrels.setdefault(x["query_id"], {})[x["record_id"]] = x
    for q in queries: qrels.setdefault(q["query_id"], {})
    dev = [q for q in queries if q["split"] == "dev"]; test = [q for q in queries if q["split"] == "test"]
    ret = R.Retriever(records)

    # --- tune feature weight on dev
    tune = {w: mean(evaluate(ret, records, dev, qrels, "weighted+demote", w), "ndcg5") for w in [1, 2, 3, 4, 5]}
    w_best = max(tune, key=lambda w: (round(tune[w], 6), -w))
    # --- tune abstention threshold on dev: midpoint between best novel score and lowest precedent score
    def top_ft(q):
        idx, ft = ret.run(q, "weighted+demote", w_feat=w_best); return float(ft.max())
    dev_nov = [top_ft(q) for q in dev if q["scenario"] == "NOVEL"]
    dev_pre = [top_ft(q) for q in dev if q["scenario"] != "NOVEL"]
    tau = round((max(dev_nov) + min(dev_pre)) / 2, 3)

    # --- RQ1 test results
    table = []
    for m, label in METHODS:
        rows = evaluate(ret, records, test, qrels, m, w_best)
        lo, hi = boot_ci([r["ndcg5"] for r in rows])
        table.append(dict(method=label, n=len(rows), ndcg5=mean(rows, "ndcg5"), ndcg5_ci=[lo, hi], mrr=mean(rows, "mrr"),
                          recall10=mean(rows, "recall10"), hard5=mean(rows, "hard5"), stale5=mean(rows, "stale5")))

    # --- paired comparisons on per-query nDCG@5 (bootstrap CI of the difference, Wilcoxon signed-rank)
    from scipy.stats import wilcoxon
    per = {m: [r["ndcg5"] for r in evaluate(ret, records, test, qrels, m, w_best)] for m, _ in METHODS}
    def paired(a, b):
        d = np.array(per[a]) - np.array(per[b]); rng = np.random.default_rng(11)
        bs = [rng.choice(d, len(d), replace=True).mean() for _ in range(2000)]
        p = float(wilcoxon(per[a], per[b]).pvalue) if np.any(d != 0) else 1.0
        return dict(diff=float(d.mean()), ci=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], wilcoxon_p=p)
    comparisons = {"weighted+demote vs keyword": paired("weighted+demote", "keyword"),
                   "weighted+demote vs kw+sem": paired("weighted+demote", "kw+sem"),
                   "hybrid+demote vs hybrid": paired("hybrid+demote", "hybrid"),
                   "weighted+demote vs hybrid+demote": paired("weighted+demote", "hybrid+demote")}

    # --- RQ2 answer contract vs unconstrained summary (test split, all queries incl. novel)
    def support(q, st):
        if q["scenario"] == "NOVEL": return False
        g = qrels[q["query_id"]].get(st["record_id"], {}).get("grade", 0)
        return g >= 3 and st.get("cause_from_record", True) is not False
    c_st = u_st = c_sup = u_sup = 0; c_abs_ok = c_abs_wrong = u_ans_novel = 0
    n_nov = sum(q["scenario"] == "NOVEL" for q in test)
    for q in test:
        idx, ft = ret.run(q, "weighted+demote", w_feat=w_best)
        cs = R.contract_summary(q, idx, ft, records, tau)
        if cs["abstain"]:
            c_abs_ok += q["scenario"] == "NOVEL"; c_abs_wrong += q["scenario"] != "NOVEL"
        for st in cs["statements"]:
            c_st += 1; c_sup += support(q, st)
        kidx, _ = ret.run(q, "keyword")
        us = R.unconstrained_summary(q, kidx, records)
        u_ans_novel += q["scenario"] == "NOVEL"
        for st in us["statements"]:
            u_st += 1; u_sup += support(q, st)
    rq2 = dict(contract=dict(statements=c_st, citation_precision=c_sup / c_st if c_st else None,
                             unsupported_rate=1 - c_sup / c_st if c_st else None,
                             correct_abstentions=c_abs_ok, novel_queries=n_nov, wrong_abstentions=c_abs_wrong),
               unconstrained=dict(statements=u_st, citation_precision=u_sup / u_st, unsupported_rate=1 - u_sup / u_st,
                                  answered_novel=u_ans_novel))

    # --- RQ3 robustness and ablation (weighted hybrid + demotion)
    rob_q = copy.deepcopy(test)
    for q in rob_q:
        q["grid_zone"] = "Z-0" + q["grid_zone"][-1]; q["bod_family"] = "DH-C"
        q["text"] = q["text"].replace(test[rob_q.index(q)]["grid_zone"], q["grid_zone"])
    rob = mean(evaluate(ret, records, rob_q, qrels, "weighted+demote", w_best), "ndcg5")
    base_fs = R.feature_score
    groups = {"grid zone": "zone", "discipline pair": "disc", "element categories": "elem",
              "clash type, phase and level": "misc", "basis-of-design family": "bod"}
    def masked(drop):
        def fs(q, r):
            s = 0.0
            if drop != "zone": s += R.zone_score(q["grid_zone"], r["grid_zone"])
            if drop != "disc": s += 1.0 if set(q["discipline_pair"]) == set(r["discipline_pair"]) else (0.5 if set(q["discipline_pair"]) & set(r["discipline_pair"]) else 0.0)
            if drop != "elem":
                A, B = set(q["element_categories"]), set(r["element_categories"]); s += len(A & B) / len(A | B)
            if drop != "misc":
                s += (0.5 if q["clash_type"] == r["clash_type"] else 0) + (0.5 if q["phase"] == r["phase"] else 0) + (0.25 if q["level"] == r["level"] else 0)
            if drop != "bod": s += 1.0 if q["bod_family"] == r["bod_family"] else 0.0
            return s
        return fs
    full = mean(evaluate(ret, records, test, qrels, "weighted+demote", w_best), "ndcg5")
    ablation = {}
    for name, key in groups.items():
        R.feature_score = masked(key)
        ablation[name] = mean(evaluate(ret, records, test, qrels, "weighted+demote", w_best), "ndcg5")
    R.feature_score = base_fs

    res = dict(config=dict(rrf_k=60, feature_weight=w_best, dev_tuning_ndcg5=tune, abstention_threshold=tau,
                           threshold_scale="structured-feature agreement score of the best-matching record (0 to 4.75)",
                           summary_layer="rule-based simulation of the answer contract (no language model)"),
               counts=dict(records=len(records), queries=len(queries), dev=len(dev), test=len(test),
                           test_with_precedent=sum(q["scenario"] != "NOVEL" for q in test), test_novel=n_nov),
               rq1=table, rq1_paired=comparisons, rq2=rq2, rq3=dict(full_ndcg5=full, no_shared_grid_or_bod_ndcg5=rob, ablation_ndcg5=ablation))
    json.dump(res, open(f"{a.out}/results.json", "w"), indent=1)
    print(json.dumps(res, indent=1))

if __name__ == "__main__":
    main()
