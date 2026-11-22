"""Old index (own TF-IDF cosine) vs the Lucene index on a fixed query set: top results, P@10, target rank, latency."""
import argparse
import statistics
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer.search import Searcher  # noqa: E402
from luceneindex.build import AKC_DIR, JOINED_DIR  # noqa: E402
from luceneindex.documents import load_field_docs  # noqa: E402
from luceneindex.searcher import LuceneSearcher  # noqa: E402


def trait(doc, name, lo=None, hi=None):
    v = doc["int"].get(name)
    return v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)


def kw(doc, field, *values):
    return any(v in doc["keyword"].get(field, []) for v in values)


def has_phrase(doc, phrase):
    return any(phrase in (" ".join(v) if isinstance(v, list) else v).lower() for v in doc["text"].values())


def long_lived(doc, years):
    return doc["int"].get("life_max", 0) >= years or doc["double"].get("life_study", 0) >= years


# query, kind (gold = predicate over the field docs, target = ids of the expected documents), value
QUERIES = [
    ("low shedding dog good with children", "gold", lambda d: trait(d, "shedding", hi=2) and trait(d, "children", lo=4)),
    ("calm apartment dog", "gold", lambda d: trait(d, "energy", hi=3) and trait(d, "adaptability", lo=4)
     and kw(d, "size", "xsmall", "small", "medium")),
    ("dog breeds from slovakia", "gold", lambda d: kw(d, "origin", "slovakia")),
    ("fci group 1 herding dog", "gold", lambda d: d["int"].get("fci_group") == 1),
    ("small dog under 10 kg that lives over 14 years", "gold",
     lambda d: d["double"].get("weight_max_kg", 99) <= 10 and long_lived(d, 14)),
    ("large guard dog good with kids", "gold",
     lambda d: kw(d, "size", "large", "xlarge") and trait(d, "watchdog", lo=4) and trait(d, "children", lo=4)),
    ("hypoallergenic dog -poodle", "gold", lambda d: trait(d, "shedding", hi=2) and "poodle" not in d["title"].lower()),
    ('"separation anxiety" in puppies', "gold", lambda d: has_phrase(d, "separation anxiety")),
    ("golden retriever hip problems", "target", ["breed:golden-retriever", "disease:Canine hip dysplasia"]),
    ("hip dysplasia golden retriever", "target", ["breed:golden-retriever", "disease:Canine hip dysplasia"]),
    ("german shepherd lifespan and diseases", "target", ["breed:german-shepherd-dog"]),
    ("rotweiler temperament", "target", ["breed:rottweiler"]),
    ("chiuaua", "target", ["breed:chihuahua"]),
    ("slovak cuvac", "target", ["breed:slovensky-cuvac"]),
    ("deutscher schaferhund", "target", ["breed:german-shepherd-dog"]),
]
SYSTEMS = ("old", "classic", "bm25")


def resolve_targets(targets, docs):
    """'disease:<title>' -> the disease document id."""
    by_title = {d["title"]: d["id"] for d in docs if d["type"] == "disease"}
    return [by_title.get(t.split(":", 1)[1], t) if t.startswith("disease:") else t for t in targets]


def old_hits(old, query):
    """Documents the old index scores at all (any query term or facet)."""
    docs = set()
    for term in old.query_terms(query):
        docs.update(no for no, _ in old.postings.get(term, []))
    return len(docs)


def run_system(name, old, new, query, k):
    if name == "old":
        return [d["id"] for _, d, _ in old.search(query, k=k)]
    new.set_similarity(name)
    return [h["id"] for h in new.search(query, k=k)["hits"]]


def latency_ms(fn, repeat):
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def evaluate(old, new, docs, k=10, repeat=5):
    by_id = {d["id"]: d for d in docs}
    rows = []
    for query, kind, value in QUERIES:
        ranked = {s: run_system(s, old, new, query, 50) for s in SYSTEMS}
        row = {"query": query, "kind": kind, "ranked": ranked}
        if kind == "gold":
            row["relevant"] = sum(1 for d in docs if value(d))
            row["p@10"] = {s: sum(1 for i in r[:k] if value(by_id[i])) / k for s, r in ranked.items()}
        else:
            targets = resolve_targets(value, docs)
            row["targets"] = targets
            row["rank"] = {s: [r.index(t) + 1 if t in r else None for t in targets] for s, r in ranked.items()}
        row["overlap@10"] = len(set(ranked["old"][:k]) & set(ranked["bm25"][:k]))
        new.set_similarity("bm25")
        row["hits"] = {"old": old_hits(old, query), "bm25": new.count(new.search(query, k=1)["query"]),
                       "strict": new.count(new.search(query, k=1, strict=True)["query"])}
        row["ms"] = {"old": latency_ms(lambda: old.search(query, k=k), repeat),
                     "bm25": latency_ms(lambda: new.search(query, k=k), repeat)}
        rows.append(row)
    return rows


def fmt_rank(ranks):
    return ", ".join("–" if r is None else str(r) for r in ranks)


def print_summary(rows, docs):
    titles = {d["id"]: d["title"] for d in docs}
    print("| query | measure | old (cosine) | Lucene classic | Lucene BM25 | overlap@10 old/BM25 "
          "| hits old / BM25 / strict | ms old / BM25 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["kind"] == "gold":
            vals = [f"{r['p@10'][s]:.1f}" for s in SYSTEMS]
            measure = "P@10"
        else:
            vals = [fmt_rank(r["rank"][s]) for s in SYSTEMS]
            measure = "rank of " + ", ".join(titles.get(t, t) for t in r["targets"])
        hits = r["hits"]
        print(f"| {r['query']} | {measure} | " + " | ".join(vals)
              + f" | {r['overlap@10']} | {hits['old']} / {hits['bm25']} / {hits['strict']}"
              + f" | {r['ms']['old']:.0f} / {r['ms']['bm25']:.0f} |")
    gold = [r for r in rows if r["kind"] == "gold"]
    print("\nmean P@10: " + ", ".join(f"{s} {statistics.mean(r['p@10'][s] for r in gold):.2f}" for s in SYSTEMS))
    print("median latency ms: old {:.0f}, bm25 {:.0f}".format(statistics.median(r["ms"]["old"] for r in rows),
                                                            statistics.median(r["ms"]["bm25"] for r in rows)))


def print_tops(rows, docs, n=5):
    by_id = {d["id"]: d for d in docs}
    for r in rows:
        print(f"\n**{r['query']}**\n\n| # | old index (cosine) | Lucene BM25 |\n|---|---|---|")
        for i in range(n):
            cells = []
            for s in ("old", "bm25"):
                ids = r["ranked"][s]
                cells.append(f"{by_id[ids[i]]['title']} *({by_id[ids[i]]['type']})*" if i < len(ids) else "")
            print(f"| {i + 1} | " + " | ".join(cells) + " |")


def main(argv=None):
    ap = argparse.ArgumentParser(description="old index vs Lucene index")
    ap.add_argument("--tops", type=int, default=5, help="top results per query to print (0 = none)")
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    old = Searcher()
    t1 = time.perf_counter()
    new = LuceneSearcher()
    t2 = time.perf_counter()
    print(f"open: old index {t1 - t0:.2f} s, Lucene {t2 - t1:.2f} s (incl. JVM start)\n")
    docs = load_field_docs(AKC_DIR, JOINED_DIR)
    rows = evaluate(old, new, docs)
    print_summary(rows, docs)
    if args.tops:
        print_tops(rows, docs, args.tops)


if __name__ == "__main__":
    main()
