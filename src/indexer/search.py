"""Cosine search over the index with switchable TF/IDF (|q| dropped, |d| precomputed); --compare shows every IDF."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import config  # noqa: E402
from indexer.idf import DEFAULT_IDF, DEFAULT_TF, IDF_METHODS, TF_METHODS, weight_key  # noqa: E402
from indexer.query_expand import expand_query  # noqa: E402
from indexer.tokenize import tokenize  # noqa: E402

INDEX_DIR = config.DATA_DIR / "index"


class Searcher:
    def __init__(self, index_dir=INDEX_DIR, index=None):
        if index is None:
            index = json.loads((index_dir / "index.json").read_text(encoding="utf-8"))
            index["docs"] = [json.loads(l) for l in (index_dir / "docs.jsonl").read_text(encoding="utf-8").split("\n") if l]
        self.index = index
        self.N, self.max_df = index["N"], index["max_df"]
        self.postings, self.df, self.norms, self.docs = index["postings"], index["df"], index["norms"], index["docs"]

    def query_terms(self, query, expand=True):
        tokens = tokenize(query) + (expand_query(query) if expand else [])
        return Counter(tokens)

    def idf(self, term, idf_name):
        return IDF_METHODS[idf_name](self.N, self.df.get(term, 0), self.max_df)

    def search(self, query, tf=DEFAULT_TF, idf=DEFAULT_IDF, k=10, doc_type=None, expand=True):
        """Top-k list of (score, doc_meta, matched_terms)."""
        tf_fn = TF_METHODS[tf]
        q = self.query_terms(query, expand)
        scores, matched = defaultdict(float), defaultdict(list)
        for term, q_tf in q.items():
            if term not in self.postings:
                continue
            w_q = tf_fn(q_tf) * self.idf(term, idf)
            if w_q == 0:
                continue
            w_idf = self.idf(term, idf)
            for no, d_tf in self.postings[term]:
                scores[no] += w_q * tf_fn(d_tf) * w_idf
                matched[no].append(term)
        norms = self.norms[weight_key(tf, idf)]
        ranked = sorted(((s / norms[no], no) for no, s in scores.items() if norms[no] > 0), reverse=True)
        out = []
        for score, no in ranked:
            d = self.docs[no]
            if doc_type and d["type"] != doc_type:
                continue
            out.append((score, d, matched[no]))
            if len(out) >= k:
                break
        return out

    def compare(self, query, tf=DEFAULT_TF, k=5, doc_type=None, methods=("classic", "smooth", "max", "none")):
        """{idf_method: top-k} and the per-term IDF table."""
        q = self.query_terms(query)
        term_table = [(t, self.df.get(t, 0), {m: round(self.idf(t, m), 3) for m in methods}) for t in q]
        results = {m: self.search(query, tf=tf, idf=m, k=k, doc_type=doc_type) for m in methods}
        return term_table, results


def fmt_results(results, md=False):
    lines = []
    for i, (score, d, terms) in enumerate(results, 1):
        if md:
            lines.append(f"| {i} | {d['title']} | {d['type']} | {score:.3f} | {' '.join(sorted(set(terms)))} |")
        else:
            lines.append(f"{i:>2}. {score:.3f}  [{d['type']}] {d['title']}   ({' '.join(sorted(set(terms)))})")
    return lines


def print_compare(query, term_table, results, md=False):
    methods = list(results)
    if md:
        print(f"**Query:** `{query}`\n")
        print("| term | df | " + " | ".join(f"idf {m}" for m in methods) + " |")
        print("|---|---|" + "---|" * len(methods))
        for t, df, idfs in term_table:
            print(f"| {t} | {df} | " + " | ".join(f"{idfs[m]:.3f}" for m in methods) + " |")
        for m in methods:
            print(f"\n*{m}*\n\n| # | document | type | score | matched terms |\n|---|---|---|---|---|")
            print("\n".join(fmt_results(results[m], md=True)))
        print()
        return
    print(f"query: {query}")
    print(f"{'term':<24}{'df':>6}  " + "".join(f"{m:>9}" for m in methods))
    for t, df, idfs in term_table:
        print(f"{t:<24}{df:>6}  " + "".join(f"{idfs[m]:>9.3f}" for m in methods))
    for m in methods:
        print(f"\n--- idf = {m} ---")
        print("\n".join(fmt_results(results[m])) or "  (no match)")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF searcher")
    ap.add_argument("query", nargs="+")
    ap.add_argument("--tf", choices=sorted(TF_METHODS), default=DEFAULT_TF)
    ap.add_argument("--idf", choices=sorted(IDF_METHODS), default=DEFAULT_IDF)
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--type", choices=("breed", "article", "list", "wiki-breed", "disease"), default=None,
                    help="restrict to one document type")
    ap.add_argument("--no-expand", action="store_true", help="do not add facet tokens derived from the query phrasing")
    ap.add_argument("--compare", action="store_true", help="show the top results of every IDF method")
    ap.add_argument("--md", action="store_true", help="markdown output (for the wiki)")
    args = ap.parse_args(argv)
    query = " ".join(args.query)

    s = Searcher()
    if args.compare:
        term_table, results = s.compare(query, tf=args.tf, k=args.k, doc_type=args.type)
        print_compare(query, term_table, results, md=args.md)
        return
    q = s.query_terms(query, not args.no_expand)
    print(f"query tokens: {' '.join(q)}")
    res = s.search(query, tf=args.tf, idf=args.idf, k=args.k, doc_type=args.type, expand=not args.no_expand)
    print("\n".join(fmt_results(res, md=args.md)) or "no match")


if __name__ == "__main__":
    main()
