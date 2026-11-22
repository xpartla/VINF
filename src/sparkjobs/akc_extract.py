"""Job 1, Spark port of extractor/run.py: latest fetch per URL, the part-1 regex extractors on the executors,
one record per canonical URL."""
import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql import types as T  # noqa: E402

from crawler import config  # noqa: E402
from sparkjobs.session import get_spark, uri, write_json  # noqa: E402

KINDS = ("breed", "article", "list", "archive")
OUT_NAMES = {"breed": "breeds", "article": "articles", "list": "pages", "archive": "archives"}
RECORD_SCHEMA = T.StructType([
    T.StructField("canonical", T.StringType()), T.StructField("url", T.StringType()),
    T.StructField("kind", T.StringType()), T.StructField("record", T.StringType()),
    T.StructField("filled", T.ArrayType(T.StringType())),
])


def extract_rows(rows):
    """(content, url, final_url, encoding) -> (canonical, url, kind, record JSON, non-empty fields)."""
    from extractor.run import canonical_of, extract

    for content, url, final_url, encoding in rows:
        html_text = bytes(content).decode(encoding or "utf-8", errors="replace")
        meta = {"url": url, "final_url": final_url}
        canonical = canonical_of(html_text, meta)
        kind, rec = extract(html_text, canonical)
        if kind is None:
            yield canonical, url, None, None, []
            continue
        filled = [k for k, v in rec.items() if k != "url" and v not in (None, "", [], {})]
        yield canonical, url, kind, json.dumps(rec, ensure_ascii=False), filled


def latest_fetches(spark, meta_glob):
    meta = spark.read.json(meta_glob)
    ok = meta.filter((F.col("status") == 200) & F.col("content_type").contains("html")
                     & F.col("file").isNotNull() & (F.col("file") != ""))
    newest = Window.partitionBy("url").orderBy(F.col("fetched_at").desc())
    return ok.withColumn("_n", F.row_number().over(newest)).filter("_n = 1").drop("_n")


def run(spark, data_dir, out_dir, compare_dir=None):
    t0 = time.time()
    pages = latest_fetches(spark, uri(data_dir, "meta", "*.jsonl")).select(
        "url", "final_url", "encoding", "file")
    raw = (spark.read.format("binaryFile").load(uri(data_dir, "raw", "*", "*", "*.html"))
           .withColumn("file", F.regexp_extract("path", r"(raw/[^/]+/[^/]+/[^/]+)$", 1)))
    joined = raw.join(F.broadcast(pages), "file").select("content", "url", "final_url", "encoding")

    extracted = spark.createDataFrame(joined.rdd.map(tuple).mapPartitions(extract_rows), RECORD_SCHEMA).cache()
    # part-1 rule: the copy fetched under the canonical URL wins, else the first by URL
    best = Window.partitionBy("canonical").orderBy((F.col("url") == F.col("canonical")).desc(), F.col("url"))
    unique = extracted.withColumn("_n", F.row_number().over(best)).filter("_n = 1").drop("_n").cache()

    for kind in KINDS:
        (unique.filter(F.col("kind") == kind).orderBy("canonical").select("record").coalesce(1)
         .write.mode("overwrite").text(uri(out_dir, OUT_NAMES[kind])))

    by_kind = {r["kind"]: r["count"] for r in unique.groupBy("kind").count().collect()}
    coverage = {}
    for r in (unique.filter(F.col("kind").isNotNull()).select("kind", F.explode("filled").alias("field"))
              .groupBy("kind", "field").count().collect()):
        coverage.setdefault(OUT_NAMES[r["kind"]], {})[r["field"]] = r["count"]
    summary = {
        "stored_html_pages": pages.count(), "read_files": extracted.count(), "unique_pages": unique.count(),
        "breeds": by_kind.get("breed", 0), "articles": by_kind.get("article", 0), "list_pages": by_kind.get("list", 0),
        "archive_pages": by_kind.get("archive", 0), "unclassified": by_kind.get(None, 0),
        "partitions": joined.rdd.getNumPartitions(), "seconds": round(time.time() - t0, 1),
        "coverage": {k: dict(sorted(v.items(), key=lambda kv: -kv[1])) for k, v in coverage.items()},
    }
    summary["alias_pages"] = summary["read_files"] - summary["unique_pages"]
    if compare_dir:
        summary["compare_with_part1"] = compare(spark, unique, compare_dir)
    write_json(uri(out_dir, "summary.json"), summary, spark)
    return summary


def compare(spark, unique, part1_dir):
    """Record-by-record diff against the single-process output of part 1 (same code -> same JSON text)."""
    result = {}
    for kind in ("breed", "article", "list"):
        old = (spark.read.text(uri(part1_dir, f"{OUT_NAMES[kind]}.jsonl"))
               .select(F.get_json_object("value", "$.url").alias("u"), F.col("value").alias("old")))
        new = unique.filter(F.col("kind") == kind).select(F.col("canonical").alias("u"), F.col("record").alias("new"))
        j = old.join(new, "u", "full_outer")
        result[OUT_NAMES[kind]] = {
            "part1": old.count(), "spark": new.count(),
            "identical": j.filter(F.col("old") == F.col("new")).count(),
            "different": j.filter(F.col("old").isNotNull() & F.col("new").isNotNull() & (F.col("old") != F.col("new"))).count(),
            "only_part1": j.filter(F.col("new").isNull()).count(),
            "only_spark": j.filter(F.col("old").isNull()).count(),
        }
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF job 1: AKC regex extraction in Spark")
    ap.add_argument("--data", default=str(config.DATA_DIR), help="dir with meta/ and raw/")
    ap.add_argument("--out", default=str(config.DATA_DIR / "spark" / "akc"))
    ap.add_argument("--compare", metavar="DIR", help="part-1 output to diff against, e.g. data/extracted")
    args = ap.parse_args(argv)
    spark = get_spark("vinf-akc-extract")
    summary = run(spark, args.data, args.out, args.compare)
    print(json.dumps({k: v for k, v in summary.items() if k != "coverage"}, indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
