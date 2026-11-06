"""Full rebuild of the inverted index: raw-tf postings, df, document norms per (tf, idf) weighting."""
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import config  # noqa: E402
from indexer.documents import load_documents  # noqa: E402
from indexer.idf import IDF_METHODS, TF_METHODS, weight_key  # noqa: E402
from indexer.tokenize import tokenize  # noqa: E402

INDEX_DIR = config.DATA_DIR / "index"


def build_index(docs):
    postings = defaultdict(dict)          # term -> {doc_no: tf}
    doc_meta, doc_len = [], []
    total_tokens = 0
    for no, d in enumerate(docs):
        tokens = tokenize(d["text"]) + list(d.get("facets", []))
        counts = Counter(tokens)
        for term, tf in counts.items():
            postings[term][no] = tf
        doc_meta.append({"id": d["id"], "type": d["type"], "title": d["title"], "url": d["url"],
                         "len": len(tokens), "unique_terms": len(counts)})
        doc_len.append(len(tokens))
        total_tokens += len(tokens)

    N = len(docs)
    df = {term: len(p) for term, p in postings.items()}
    max_df = max(df.values()) if df else 1
    norms = {weight_key(tf, idf): [0.0] * N for tf in TF_METHODS for idf in IDF_METHODS}
    for term, p in postings.items():
        idf_w = {idf: fn(N, df[term], max_df) for idf, fn in IDF_METHODS.items()}
        for no, tf in p.items():
            tf_w = {tf_name: fn(tf) for tf_name, fn in TF_METHODS.items()}
            for tf_name, wt in tf_w.items():
                for idf_name, wi in idf_w.items():
                    norms[weight_key(tf_name, idf_name)][no] += (wt * wi) ** 2
    for key in norms:
        norms[key] = [math.sqrt(x) for x in norms[key]]

    return {
        "N": N, "max_df": max_df, "total_tokens": total_tokens,
        "postings": {term: sorted(p.items()) for term, p in postings.items()},
        "df": df, "norms": norms, "doc_len": doc_len, "docs": doc_meta,
    }


def save_index(index, index_dir=INDEX_DIR):
    index_dir.mkdir(parents=True, exist_ok=True)
    docs = index.pop("docs")
    with open(index_dir / "docs.jsonl", "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(index_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    index["docs"] = docs


def summary(index, seconds, index_dir=INDEX_DIR):
    docs = index["docs"]
    by_type = Counter(d["type"] for d in docs)
    size_mb = sum(p.stat().st_size for p in index_dir.glob("*")) / 1e6
    top = sorted(index["df"].items(), key=lambda kv: -kv[1])[:12]
    lines = [
        f"index built in {seconds:.1f}s: {index['N']} documents {dict(by_type)}",
        f"unique terms {len(index['postings'])}, total tokens {index['total_tokens']}, "
        f"postings {sum(len(p) for p in index['postings'].values())}, max_df {index['max_df']}",
        f"avg document length {index['total_tokens'] / max(index['N'], 1):.0f} tokens, index files {size_mb:.1f} MB in {index_dir}",
        "most frequent terms (df): " + ", ".join(f"{t} {n}" for t, n in top),
    ]
    return "\n".join(lines)


def main():
    t0 = time.time()
    docs = load_documents(config.DATA_DIR / "extracted")
    if not docs:
        sys.exit("no documents in data/extracted/ - run src/extractor/run.py first")
    index = build_index(docs)
    save_index(index)
    text = summary(index, time.time() - t0)
    (INDEX_DIR / "stats.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
