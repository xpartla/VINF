"""Dog breed advisor search on the Lucene index: natural queries (default) or Lucene query syntax (--syntax)."""
import argparse
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from luceneindex.plan import satisfies  # noqa: E402
from luceneindex.schema import DOC_TYPES, SORT_FIELDS  # noqa: E402
from luceneindex.searcher import LuceneSearcher  # noqa: E402


def _span(f, name, unit):
    lo, hi = f.get(f"{name}_min_{unit}"), f.get(f"{name}_max_{unit}")
    if lo is None:
        return ""
    return f"{lo:g} {unit}" if lo == hi else f"{lo:g}-{hi:g} {unit}"


def card(hit):
    """One-line summary of the stored fields."""
    f, parts = hit["fields"], []
    if hit["type"] in ("breed", "wiki-breed"):
        parts += [f.get("size", [""])[0], f.get("group", [""])[0], ", ".join(f.get("origin", [])[:2])]
        if "fci_group" in f:
            parts.append(f"FCI {f['fci_group']}")
        parts += [_span(f, "weight", "kg"), _span(f, "height", "cm")]
        if "life_min" in f:
            parts.append(f"life {f['life_min']}-{f['life_max']}")
        if "life_study" in f:
            parts.append(f"measured {f['life_study']:g} y")
        if "extinct" in f:
            parts.append("extinct")
    elif hit["type"] == "article":
        parts += [f.get("category", [""])[0], str(f.get("published", ""))]
    elif hit["type"] == "list":
        parts.append(f"{len(f.get('breed', []))} breeds")
    return " · ".join(p for p in parts if p)


def constraint_marks(constraints, hit):
    return " ".join(("+" if satisfies(c, hit["fields"]) else "-") + c["label"] for c in constraints)


def print_result(s, res, args, seconds):
    p = res["plan"]
    if p:
        print(f"text: {p['text']!r}  phrases: {p['phrases']}  exclude: {p['exclude']}")
        print(f"constraints ({'filter' if args.strict else 'boost'}): {[c['label'] for c in res['constraints']]}"
              + (f", ignored (value not in the index): {res['ignored']}" if res["ignored"] else ""))
        if res["misspelled"]:
            print("fuzzy: " + ", ".join(f"{w} -> {'/'.join(s.fuzzy_expansions(w)) or '?'}" for w in res["misspelled"]))
    if args.show_query:
        print(f"lucene query: {res['query'].toString()}")
    print(f"{'' if res['exact'] else '>= '}{res['total']} hits, {seconds * 1000:.0f} ms, similarity {s.similarity}")
    for i, h in enumerate(res["hits"], 1):
        line = f"{i:>2}. {h['score']:7.3f}  [{h['type']}] {h['title']}"
        info = card(h)
        print(line + (f"   ({info})" if info else ""))
        marks = constraint_marks(res["constraints"], h)
        if marks:
            print(f"{'':13}{marks}")
        if args.terms:
            print(f"{'':13}{' '.join(s.matched_terms(res['query'], h['doc']))}")
    if args.explain:
        h = res["hits"][args.explain - 1]
        print(f"\nexplanation of hit {args.explain} ({h['title']}):\n{s.explain(res['query'], h['doc']).toString()}")


def run_query(s, text, args):
    t0 = time.perf_counter()
    if args.syntax or text.startswith("lucene:"):
        text = text[len("lucene:"):].strip() if text.startswith("lucene:") else text
        res = s.syntax_search(text, k=args.k, doc_type=args.type, sort=args.sort)
    else:
        res = s.search(text, k=args.k, doc_type=args.type, strict=args.strict, sort=args.sort)
    print_result(s, res, args, time.perf_counter() - t0)


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF dog breed advisor (Lucene)")
    ap.add_argument("query", nargs="*")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--type", choices=DOC_TYPES, default=None, help="restrict to one document type")
    ap.add_argument("--strict", action="store_true", help="constraints filter (AND) instead of boosting")
    ap.add_argument("--syntax", action="store_true", help="Lucene query syntax instead of a natural query")
    ap.add_argument("--similarity", choices=("bm25", "classic"), default="bm25")
    ap.add_argument("--sort", choices=sorted(SORT_FIELDS), default=None, help="sort by a field instead of the score")
    ap.add_argument("--terms", action="store_true", help="show the field:term pairs that scored")
    ap.add_argument("--explain", type=int, default=0, metavar="N", help="print the Lucene explanation of hit N")
    ap.add_argument("--show-query", action="store_true", help="print the Lucene query")
    ap.add_argument("-i", "--interactive", action="store_true", help="read queries from stdin ('lucene:' = syntax)")
    args = ap.parse_args(argv)
    s = LuceneSearcher(similarity=args.similarity)
    if args.query:
        run_query(s, " ".join(args.query), args)
    if args.interactive:
        for line in sys.stdin:
            if line.strip():
                run_query(s, line.strip(), args)
                print()


if __name__ == "__main__":
    main()
