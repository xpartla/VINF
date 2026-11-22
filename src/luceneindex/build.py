"""Full rebuild of the Lucene index from the Spark output (data/spark/akc + data/spark/joined) into data/lucene/."""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import config  # noqa: E402
from luceneindex import env  # noqa: E402
from luceneindex.documents import load_field_docs  # noqa: E402
from luceneindex.schema import OMIT_NORMS, STORED_TEXT, TEXT_FIELDS  # noqa: E402

LUCENE_DIR = config.DATA_DIR / "lucene"
INDEX_DIR = LUCENE_DIR / "index"
AKC_DIR = config.DATA_DIR / "spark" / "akc"
JOINED_DIR = config.DATA_DIR / "spark" / "joined"


def _no_norms_type():
    from org.apache.lucene.document import FieldType, TextField

    ft = FieldType(TextField.TYPE_NOT_STORED)
    ft.setOmitNorms(True)
    ft.freeze()
    return ft


def to_lucene(doc, no_norms=None):
    from org.apache.lucene.document import Document, DoubleField, Field, IntField, StoredField, StringField, TextField

    no_norms = no_norms or _no_norms_type()
    d = Document()
    d.add(StringField("id", doc["id"], Field.Store.YES))
    d.add(StringField("type", doc["type"], Field.Store.YES))
    d.add(StoredField("url", doc["url"]))
    for field, value in doc["text"].items():
        store = Field.Store.YES if field in STORED_TEXT else Field.Store.NO
        for v in value if isinstance(value, list) else [value]:
            if v:
                d.add(Field(field, v, no_norms) if field in OMIT_NORMS else TextField(field, v, store))
    for field, values in doc["keyword"].items():
        for v in values:
            d.add(StringField(field, v, Field.Store.YES))
    for field, v in doc["int"].items():
        d.add(IntField(field, v, Field.Store.YES))       # points (range queries) + doc values (sorting)
    for field, v in doc["double"].items():
        d.add(DoubleField(field, v, Field.Store.YES))
    return d


def write_index(docs, directory):
    from org.apache.lucene.index import IndexWriter, IndexWriterConfig
    from org.apache.lucene.search.similarities import BM25Similarity

    cfg = IndexWriterConfig(env.build_analyzers()["fields"])
    cfg.setOpenMode(IndexWriterConfig.OpenMode.CREATE)
    cfg.setSimilarity(BM25Similarity())
    writer = IndexWriter(directory, cfg)
    no_norms = _no_norms_type()
    for doc in docs:
        writer.addDocument(to_lucene(doc, no_norms))
    writer.forceMerge(1)
    writer.commit()
    writer.close()


def coverage(docs):
    """{field: {doc type: number of documents with the field}}."""
    out = defaultdict(Counter)
    for d in docs:
        fields = [f for f, v in d["text"].items() if v] + list(d["keyword"]) + list(d["int"]) + list(d["double"])
        for f in fields:
            out[f][d["type"]] += 1
    return {f: dict(c) for f, c in sorted(out.items())}


def term_stats(directory):
    from org.apache.lucene.index import DirectoryReader, MultiTerms

    reader = DirectoryReader.open(directory)
    out = {}
    for field in TEXT_FIELDS:
        terms = MultiTerms.getTerms(reader, field)
        if terms is not None:
            docs = reader.getDocCount(field)
            out[field] = {"docs": docs, "terms": terms.size(), "tokens": terms.getSumTotalTermFreq(),
                          "avg_len": round(terms.getSumTotalTermFreq() / max(docs, 1), 1)}
    n = reader.numDocs()
    reader.close()
    return n, out


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF Lucene index builder")
    ap.add_argument("--akc", type=Path, default=AKC_DIR)
    ap.add_argument("--joined", type=Path, default=JOINED_DIR)
    ap.add_argument("--out", type=Path, default=INDEX_DIR)
    args = ap.parse_args(argv)
    if not (args.joined / "breeds").is_dir():
        sys.exit(f"no {args.joined}/breeds - run the Spark jobs first (src/sparkjobs/)")
    env.init()
    from java.nio.file import Paths
    from org.apache.lucene.store import FSDirectory

    t0 = time.time()
    docs = load_field_docs(args.akc, args.joined)
    t1 = time.time()
    directory = FSDirectory.open(Paths.get(str(args.out.resolve())))
    write_index(docs, directory)
    t2 = time.time()
    n, terms = term_stats(directory)
    size_mb = sum(p.stat().st_size for p in args.out.glob("*")) / 1e6
    stats = {"documents": n, "by_type": dict(Counter(d["type"] for d in docs)), "load_s": round(t1 - t0, 1),
             "index_s": round(t2 - t1, 1), "size_mb": round(size_mb, 1), "text_fields": terms, "coverage": coverage(docs)}
    (args.out.parent / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"lucene index: {n} documents {stats['by_type']} in {args.out}")
    print(f"records loaded in {stats['load_s']} s, indexed in {stats['index_s']} s, {size_mb:.1f} MB")
    for field, s in terms.items():
        print(f"  {field:<12} docs {s['docs']:>5}  terms {s['terms']:>6}  avg length {s['avg_len']:>7}")


if __name__ == "__main__":
    main()
