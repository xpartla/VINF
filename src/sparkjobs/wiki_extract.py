"""Job 2, Wikipedia dump: `scan` reads the bz2 dump once and keeps id/ns/title/redirect of every page plus the wikitext
of dog-related articles (JVM regexes); `parse` turns those articles into breed and disease records (Python regexes)."""
import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import functions as F  # noqa: E402
from pyspark.sql import types as T  # noqa: E402

from crawler import config  # noqa: E402
from sparkjobs.session import get_spark, uri, write_json  # noqa: E402

DEFAULT_DUMP = config.DATA_DIR / "wiki" / "enwiki-20261001" / "*.bz2"
DEFAULT_OUT = config.DATA_DIR / "spark" / "wiki"

# Java regexes, evaluated inside the JVM on every <page> record
TITLE_RE = r"<title>([^<]*)</title>"
NS_RE = r"<ns>(-?\d+)</ns>"
ID_RE = r"<ns>-?\d+</ns>\s*<id>(\d+)</id>"
REDIRECT_RE = r'<redirect title="([^"]*)"'
TEXT_RE = r"(?s)<text\b[^>]*>(.*)</text>"
BREED_INFOBOX_RE = r"(?i)\{\{\s*infobox[ _]*dog[ _]*breed"
DOG_CATEGORY_RE = r"(?i)\[\[\s*category\s*:[^\]|]*\b(?:dogs?|canine)\b"
XML_ENTITIES = (("&quot;", '"'), ("&#039;", "'"), ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&amp;", "&"))


def xml_unescape(col):
    for entity, char in XML_ENTITIES:
        col = F.regexp_replace(col, entity, char)
    return col


def scan(spark, dump_glob, out_dir):
    """One pass over the dump -> out/pages (parquet: every page, wikitext only for selected articles)."""
    t0 = time.time()
    raw = spark.read.option("lineSep", "</page>").text(dump_glob)
    page = F.col("value")
    pages = raw.filter(page.contains("<page>")).select(
        F.regexp_extract(page, ID_RE, 1).cast("long").alias("id"),
        F.regexp_extract(page, NS_RE, 1).cast("int").alias("ns"),
        xml_unescape(F.regexp_extract(page, TITLE_RE, 1)).alias("title"),
        F.when(page.contains("<redirect "), xml_unescape(F.regexp_extract(page, REDIRECT_RE, 1))).alias("redirect"),
        F.length(page).alias("xml_chars"),
        page.rlike(BREED_INFOBOX_RE).alias("breed_infobox"),
        page.rlike(DOG_CATEGORY_RE).alias("dog_category"),
        page,
    )
    selected = (F.col("ns") == 0) & F.col("redirect").isNull() & (F.col("breed_infobox") | F.col("dog_category"))
    pages = pages.withColumn("text", F.when(selected, F.regexp_extract(page, TEXT_RE, 1))).drop("value")
    pages.write.mode("overwrite").parquet(uri(out_dir, "pages"))
    stats = scan_stats(spark.read.parquet(uri(out_dir, "pages")))
    stats.update({"dump": dump_glob, "input_partitions": raw.rdd.getNumPartitions(), "seconds": round(time.time() - t0, 1)})
    write_json(uri(out_dir, "scan_stats.json"), stats, spark)
    return stats


def scan_stats(pages):
    row = pages.agg(
        F.count("*").alias("pages"),
        F.countDistinct("id").alias("distinct_ids"),
        F.sum("xml_chars").alias("xml_chars"),
        F.sum(F.when(F.col("ns") == 0, 1).otherwise(0)).alias("ns0_pages"),
        F.sum(F.when((F.col("ns") == 0) & F.col("redirect").isNull(), 1).otherwise(0)).alias("ns0_articles"),
        F.sum(F.when((F.col("ns") == 0) & F.col("redirect").isNotNull(), 1).otherwise(0)).alias("ns0_redirects"),
        F.sum(F.when(F.col("text").isNotNull(), 1).otherwise(0)).alias("selected_articles"),
        F.sum(F.when(F.col("text").isNotNull() & F.col("breed_infobox"), 1).otherwise(0)).alias("selected_breed_infobox"),
        F.sum(F.when(F.col("text").isNotNull() & F.col("dog_category"), 1).otherwise(0)).alias("selected_dog_category"),
    ).first().asDict()
    return row


PARSED_SCHEMA = T.StructType([T.StructField("kind", T.StringType()), T.StructField("title", T.StringType()),
                              T.StructField("record", T.StringType()), T.StructField("jvm_infobox", T.BooleanType()),
                              T.StructField("parsed_infobox", T.BooleanType())])


def parse_rows(rows):
    from wiki.page import parse_page

    for page_id, title, text, jvm_infobox in rows:
        kind, rec = parse_page(page_id, title, text)
        yield (kind, title, json.dumps(rec, ensure_ascii=False) if rec is not None else None, jvm_infobox,
               bool(rec and rec.get("has_infobox")))


def parse(spark, out_dir):
    """out/pages -> out/{breeds,diseases,other_dog_pages}/ (JSON lines) + out/redirects (parquet)."""
    t0 = time.time()
    pages = spark.read.parquet(uri(out_dir, "pages"))
    selected = pages.filter(F.col("text").isNotNull()).select("id", "title", "text", "breed_infobox")
    parsed = spark.createDataFrame(selected.rdd.map(tuple).mapPartitions(parse_rows), PARSED_SCHEMA).cache()
    for kind in ("breed", "disease"):
        (parsed.filter(F.col("kind") == kind).orderBy("title").select("record").coalesce(1)
         .write.mode("overwrite").text(uri(out_dir, kind + "s")))
    (parsed.filter(F.col("kind") == "other").orderBy("title").select("title").coalesce(1)
     .write.mode("overwrite").text(uri(out_dir, "other_dog_pages")))

    redirects = (pages.filter((F.col("ns") == 0) & F.col("redirect").isNotNull())
                 .select("title", F.regexp_replace("redirect", "#.*$", "").alias("target"),
                         F.regexp_extract("redirect", "#(.*)$", 1).alias("anchor")))
    redirects.write.mode("overwrite").parquet(uri(out_dir, "redirects"))

    counts = {r["kind"]: r["count"] for r in parsed.groupBy("kind").count().collect()}
    lost = parsed.filter(F.col("jvm_infobox") & ~F.col("parsed_infobox"))
    stats = {"parsed_pages": sum(counts.values()), "by_kind": counts,
             "breeds_without_infobox": parsed.filter((F.col("kind") == "breed") & ~F.col("parsed_infobox")).count(),
             "infobox_seen_by_jvm_not_parsed": sorted(r["title"] for r in lost.select("title").collect()),
             "redirects": spark.read.parquet(uri(out_dir, "redirects")).count(),
             "seconds": round(time.time() - t0, 1)}
    write_json(uri(out_dir, "parse_stats.json"), stats, spark)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF job 2: Wikipedia dump with regexes in Spark")
    ap.add_argument("stage", choices=("scan", "parse", "all"))
    ap.add_argument("--dump", default=str(DEFAULT_DUMP), help="bz2/xml dump file(s), glob allowed")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    spark = get_spark("vinf-wiki-" + args.stage)
    dump = uri(args.dump)
    if args.stage in ("scan", "all"):
        print(json.dumps(scan(spark, dump, args.out), indent=2))
    if args.stage in ("parse", "all"):
        print(json.dumps(parse(spark, args.out), indent=2))
    spark.stop()


if __name__ == "__main__":
    main()
