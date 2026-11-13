"""Rankers, fusion, demotion, abstention and the answer contract."""
import math, re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

TOK = re.compile(r"[a-z0-9]+")

def text_of(r):
    return " ".join([r.get("symptom", r.get("text", "")), r.get("root_cause", ""), r.get("resolution", ""),
                     " ".join(r["element_categories"]), " ".join(r["discipline_pair"])]).lower()

def toks(s):
    return TOK.findall(s.lower())

class BM25:
    def __init__(self, docs, k1=1.2, b=0.75):
        self.docs = [toks(d) for d in docs]; self.k1, self.b = k1, b
        self.avg = sum(map(len, self.docs)) / len(self.docs); self.N = len(self.docs)
        self.df = {}
        for d in self.docs:
            for t in set(d): self.df[t] = self.df.get(t, 0) + 1
    def scores(self, q):
        out = np.zeros(self.N)
        for t in set(toks(q)):
            if t not in self.df: continue
            idf = math.log(1 + (self.N - self.df[t] + 0.5) / (self.df[t] + 0.5))
            for i, d in enumerate(self.docs):
                f = d.count(t)
                if f: out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * len(d) / self.avg))
        return out

class LSA:
    def __init__(self, docs, dims=40, seed=0):
        self.v = TfidfVectorizer(token_pattern=r"[a-z0-9]+", sublinear_tf=True)
        X = self.v.fit_transform(docs)
        self.svd = TruncatedSVD(n_components=min(dims, X.shape[1] - 1), random_state=seed)
        self.D = self._norm(self.svd.fit_transform(X))
    @staticmethod
    def _norm(M):
        n = np.linalg.norm(M, axis=1, keepdims=True); n[n == 0] = 1; return M / n
    def scores(self, q):
        v = self._norm(self.svd.transform(self.v.transform([q])))
        return (self.D @ v.T).ravel()

def zone_score(a, b):
    if a == b: return 1.0
    ca, ra = a.split("-"); cb, rb = b.split("-")
    cols = "ABCDEFGHJK"
    if ca in cols and cb in cols and ra.isdigit() and rb.isdigit():
        if abs(cols.index(ca) - cols.index(cb)) + abs(int(ra) - int(rb)) == 1: return 0.5
    return 0.0

def feature_score(q, r):
    s = zone_score(q["grid_zone"], r["grid_zone"])
    s += 1.0 if set(q["discipline_pair"]) == set(r["discipline_pair"]) else (0.5 if set(q["discipline_pair"]) & set(r["discipline_pair"]) else 0.0)
    a, b = set(q["element_categories"]), set(r["element_categories"])
    s += len(a & b) / len(a | b)
    s += 0.5 if q["clash_type"] == r["clash_type"] else 0.0
    s += 1.0 if q["bod_family"] == r["bod_family"] else 0.0
    s += 0.5 if q["phase"] == r["phase"] else 0.0
    s += 0.25 if q["level"] == r["level"] else 0.0
    return s  # max 4.75

def ranks(scores):
    order = np.argsort(-scores, kind="stable")
    rk = np.empty(len(scores), int); rk[order] = np.arange(1, len(scores) + 1)
    return rk

def rrf(rank_lists, weights, k=60):
    return sum(w / (k + rk) for rk, w in zip(rank_lists, weights))

def is_stale(q, r):
    return r["superseded"] or r["bod_version"] < q["bod_version"]

def order(scores, records, q, demote):
    idx = list(np.argsort(-scores, kind="stable"))
    if demote:
        cur = [i for i in idx if not is_stale(q, records[i])]
        old = [i for i in idx if is_stale(q, records[i])]
        idx = cur + old
    return idx

class Retriever:
    def __init__(self, records):
        self.records = records
        docs = [text_of(r) for r in records]
        self.bm25 = BM25(docs); self.lsa = LSA(docs)
    def run(self, q, method, w_feat=3.0, k=60):
        qt = text_of(q)
        kw = self.bm25.scores(qt); sem = self.lsa.scores(qt)
        ft = np.array([feature_score(q, r) for r in self.records])
        R = self.records
        if method == "keyword": return order(kw, R, q, False), ft
        if method == "semantic": return order(sem, R, q, False), ft
        if method == "kw+sem": return order(rrf([ranks(kw), ranks(sem)], [1, 1], k), R, q, False), ft
        if method == "feature": return order(ft + 1e-6 * kw, R, q, False), ft
        if method == "hybrid": return order(rrf([ranks(kw), ranks(sem), ranks(ft)], [1, 1, 1], k), R, q, False), ft
        if method == "hybrid+demote": return order(rrf([ranks(kw), ranks(sem), ranks(ft)], [1, 1, 1], k), R, q, True), ft
        if method == "weighted+demote": return order(rrf([ranks(kw), ranks(sem), ranks(ft)], [1, 1, w_feat], k), R, q, True), ft
        raise ValueError(method)

# ---------- answer contract (rule-based simulation of the summary layer) ----------
def contract_summary(q, ranked, ft, records, tau, top=3):
    """Cite only current records whose engineering context supports the match; abstain otherwise.
    Each statement reports only the cause and fix written in the cited record."""
    if ft[ranked[0]] < tau and max(ft) < tau:
        return dict(abstain=True, statements=[])
    out = []
    for i in ranked[:top]:
        r = records[i]
        if ft[i] < tau or is_stale(q, r):
            continue
        out.append(dict(record_id=r["record_id"], cause=r["root_cause"] or None, fix=r["resolution"]))
    return dict(abstain=len(out) == 0, statements=out)

def unconstrained_summary(q, ranked, records, top=3):
    """Baseline: summarizes the top records of keyword search, never abstains, and fills a missing
    cause with the cause from the highest-ranked record that has one (a typical unsupported inference)."""
    rs = [records[i] for i in ranked[:top]]
    fallback = next((r["root_cause"] for r in rs if r["root_cause"]), None)
    return dict(abstain=False, statements=[dict(record_id=r["record_id"], cause=r["root_cause"] or fallback,
                                                cause_from_record=bool(r["root_cause"]), fix=r["resolution"]) for r in rs])
