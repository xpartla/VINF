"""Job 3: AKC breeds x Wikipedia breed articles (name keys, priority cascade), then the Health-section links of the
joined articles x dog-disease articles (through redirects)."""
import argparse
import json
import random
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pyspark.sql import Window  # noqa: E402
from pyspark.sql import functions as F  # noqa: E402

from crawler import config  # noqa: E402
from sparkjobs.session import get_spark, uri, write_json  # noqa: E402

AKC_DIR = config.DATA_DIR / "spark" / "akc"
WIKI_DIR = config.DATA_DIR / "spark" / "wiki"
OUT_DIR = config.DATA_DIR / "spark" / "joined"

# (AKC key kind, wiki key kind) -> priority, lower wins; nickname x *_variant is too loose and not joined
PRIORITY = {
    ("slug", "akc_url"): 0,
    ("name", "title"): 1,
    ("name", "redirect"): 2,
    ("name", "infobox_name"): 3,
    ("name", "title_variant"): 4, ("name", "redirect_variant"): 4, ("variant", "title"): 4,
    ("variant", "redirect"): 4, ("variant", "title_variant"): 4, ("variant", "redirect_variant"): 4,
    ("variant", "infobox_name"): 5,
    ("nickname", "title"): 6, ("nickname", "redirect"): 6,
    ("nickname", "infobox_name"): 7,
}
WIKI_FIELDS = ("page_id", "title", "url", "has_infobox", "names", "altnames", "nicknames", "country",
               "origin_countries", "categories", "fci_number", "fci_group", "registries", "height_min_cm",
               "height_max_cm", "weight_min_kg", "weight_max_kg", "life_expectancy_study",
               "litter_min", "litter_max", "coat", "colour", "extinct", "lead", "temperament", "health", "history",
               "appearance")
ATTRIBUTES = ("country", "origin_countries", "altnames", "nicknames", "fci_number", "fci_group", "registries",
              "height_min_cm", "weight_min_kg", "life_expectancy_study", "litter_min", "coat", "colour",
              "lead", "temperament", "health", "history", "appearance", "diseases")


def akc_key_rows(line):
    from wiki.names import akc_keys

    rec = json.loads(line)
    yield rec["slug"], rec["slug"], "slug"
    for key, kind in akc_keys(rec["name"], rec.get("nicknames") or []):
        yield rec["slug"], key, kind


def wiki_key_rows(line):
    from wiki.names import wiki_name_keys, wiki_title_keys

    rec = json.loads(line)
    pid = rec["page_id"]
    for key, kind in wiki_title_keys(rec["title"]):
        yield pid, key, "title" if kind == "exact" else "title_variant"
    for key in wiki_name_keys((rec.get("names") or []) + (rec.get("altnames") or []) + (rec.get("nicknames") or [])):
        yield pid, key, "infobox_name"
    if rec.get("akc_slug"):
        yield pid, rec["akc_slug"], "akc_url"


def redirect_key_rows(row):
    from wiki.names import wiki_title_keys

    for key, kind in wiki_title_keys(row["redirect"]):
        yield row["page_id"], key, "redirect" if kind == "exact" else "redirect_variant"


def priority_col():
    mapping = F.create_map(*[x for (a, w), p in PRIORITY.items() for x in (F.lit(f"{a}|{w}"), F.lit(p))])
    return mapping[F.concat_ws("|", "akc_kind", "wiki_kind")]


def match_breeds(spark, akc_lines, wiki_breeds, redirects):
    akc_keys = spark.createDataFrame(akc_lines.rdd.flatMap(lambda r: akc_key_rows(r.value)),
                                     "slug string, key string, akc_kind string")
    wiki_keys = spark.createDataFrame(wiki_breeds.select("value").rdd.flatMap(lambda r: wiki_key_rows(r.value)),
                                      "page_id long, key string, wiki_kind string")
    to_breed = redirects.join(F.broadcast(wiki_breeds.select("page_id", F.col("title").alias("target"))), "target")
    redirect_keys = spark.createDataFrame(
        to_breed.select("page_id", F.col("title").alias("redirect")).rdd.flatMap(redirect_key_rows),
        "page_id long, key string, wiki_kind string")
    keys = wiki_keys.unionByName(redirect_keys)

    cand = (akc_keys.join(keys, "key").withColumn("priority", priority_col()).filter(F.col("priority").isNotNull())
            .join(wiki_breeds.select("page_id", "title", "has_infobox"), "page_id"))
    return best_page(cand), best_page(cand.filter(F.col("priority") > 0)).select("slug", "page_id")


def best_page(cand):
    """One row per AKC slug: the page with the lowest priority (then infobox, more matching keys, lower id)."""
    per_pair = cand.groupBy("slug", "page_id", "title", "has_infobox").agg(
        F.min("priority").alias("priority"), F.count("*").alias("n_keys"),
        F.min_by(F.concat_ws("|", "akc_kind", "wiki_kind"), "priority").alias("method"),
        F.min_by("key", "priority").alias("key"))
    best_first = Window.partitionBy("slug").orderBy("priority", F.col("has_infobox").desc(), F.col("n_keys").desc(),
                                                   "page_id")
    at_best = Window.partitionBy("slug", "priority")
    ranked = (per_pair.withColumn("rank", F.row_number().over(best_first))
              .withColumn("ties", F.count("*").over(at_best)))
    alternatives = (ranked.filter("rank > 1").groupBy("slug")
                    .agg(F.sort_array(F.collect_list(F.struct("priority", "title"))).alias("alternatives")))
    return (ranked.filter("rank = 1").drop("rank", "has_infobox").join(alternatives, "slug", "left")
            .withColumn("ambiguous", F.col("ties") > 1))


def link_diseases(wiki_breeds, diseases, redirects):
    """(page_id, link, resolved, via_redirect, disease_id) for every Health-section link of every wiki breed."""
    links = wiki_breeds.select("page_id", F.explode("health_links").alias("link"))
    red = redirects.select(F.col("title").alias("link"), F.col("target"))
    resolved = (links.join(red, "link", "left")
                .withColumn("resolved", F.coalesce("target", "link"))
                .withColumn("via_redirect", F.col("target").isNotNull()).drop("target"))
    dis = diseases.select(F.col("title").alias("resolved"), F.col("page_id").alias("disease_id"),
                          F.col("url").alias("disease_url"))
    return resolved.join(F.broadcast(dis), "resolved", "left")


def merge_record(row):
    rec = json.loads(row["akc"])
    if row["wiki"] is None:
        rec["wiki"] = None
        return json.dumps(rec, ensure_ascii=False)
    w = json.loads(row["wiki"])
    wiki = {k: w.get(k) for k in WIKI_FIELDS}
    wiki["match"] = {"priority": row["priority"], "method": row["method"], "key": row["key"],
                     "ambiguous": row["ambiguous"]}
    wiki["diseases"] = [{"title": d["title"], "url": d["url"]} for d in sorted(row["diseases"] or [], key=lambda d: d["title"])]
    rec["wiki"] = wiki
    return json.dumps(rec, ensure_ascii=False)


def with_diseases(wiki_record_line, diseases):
    w = json.loads(wiki_record_line)
    out = {k: w.get(k) for k in WIKI_FIELDS}
    out["diseases"] = sorted(diseases or [], key=lambda d: d["title"])
    return json.dumps(out, ensure_ascii=False)


def run(spark, akc_dir, wiki_dir, out_dir):
    t0 = time.time()
    akc_lines = spark.read.text(uri(akc_dir, "breeds"))
    akc = akc_lines.select(F.get_json_object("value", "$.slug").alias("slug"),
                           F.get_json_object("value", "$.name").alias("akc_name"), F.col("value").alias("akc"))
    wiki_lines = spark.read.text(uri(wiki_dir, "breeds"))
    wiki_breeds = spark.read.json(wiki_lines.rdd.map(lambda r: r.value)).join(
        wiki_lines.select(F.get_json_object("value", "$.page_id").cast("long").alias("page_id"), "value"), "page_id")
    diseases = spark.read.json(uri(wiki_dir, "diseases"))
    redirects = spark.read.parquet(uri(wiki_dir, "redirects"))

    matches, name_only = match_breeds(spark, akc_lines, wiki_breeds, redirects)
    matches = matches.cache()
    links = link_diseases(wiki_breeds, diseases, redirects).cache()
    breed_diseases = (links.filter(F.col("disease_id").isNotNull()).dropDuplicates(["page_id", "disease_id"])
                      .groupBy("page_id").agg(F.collect_list(F.struct(F.col("resolved").alias("title"),
                                                                      F.col("disease_url").alias("url"))).alias("diseases")))

    joined = (akc.join(matches.select("slug", "page_id", "priority", "method", "key", "ambiguous"), "slug", "left")
              .join(wiki_breeds.select("page_id", F.col("value").alias("wiki")), "page_id", "left")
              .join(breed_diseases, "page_id", "left"))
    merged = joined.orderBy("slug").rdd.map(merge_record)
    spark.createDataFrame(merged.map(lambda s: (s,)), "value string").coalesce(1).write.mode("overwrite").text(
        uri(out_dir, "breeds"))

    joined_pages = matches.select("page_id").distinct()
    wiki_only = (wiki_breeds.join(joined_pages, "page_id", "left_anti").join(breed_diseases, "page_id", "left")
                 .orderBy("title").rdd.map(lambda r: (with_diseases(r["value"], [d.asDict() for d in r["diseases"] or []]),)))
    spark.createDataFrame(wiki_only, "value string").coalesce(1).write.mode("overwrite").text(
        uri(out_dir, "wiki_only_breeds"))

    linked = links.filter(F.col("disease_id").isNotNull()).dropDuplicates(["page_id", "disease_id"])
    akc_names = matches.join(akc.select("slug", "akc_name"), "slug").select("page_id", "akc_name")
    per_disease = (linked.join(wiki_breeds.select("page_id", F.col("title").alias("breed_title")), "page_id")
                   .join(akc_names, "page_id", "left")
                   .groupBy("disease_id").agg(F.sort_array(F.collect_set("breed_title")).alias("wiki_breeds"),
                                              F.sort_array(F.collect_set("akc_name")).alias("akc_breeds")))
    disease_out = (diseases.join(per_disease.withColumnRenamed("disease_id", "page_id"), "page_id")
                   .orderBy("title").select(F.to_json(F.struct(*sorted(set(diseases.columns) | {"wiki_breeds", "akc_breeds"})))))
    disease_out.coalesce(1).write.mode("overwrite").text(uri(out_dir, "diseases"))

    stats = statistics(spark, matches, name_only, links, akc, wiki_breeds, diseases, uri(out_dir, "breeds"))
    stats["seconds"] = round(time.time() - t0, 1)
    write_json(uri(out_dir, "join_stats.json"), stats, spark)
    return stats


def overlap(a_lo, a_hi, b_lo, b_hi, tolerance=0.0):
    if None in (a_lo, a_hi, b_lo, b_hi):
        return None
    return a_lo <= b_hi * (1 + tolerance) and b_lo <= a_hi * (1 + tolerance)


def statistics(spark, matches, name_only, links, akc, wiki_breeds, diseases, joined_path):
    m = [r.asDict(recursive=True) for r in matches.collect()]
    n_akc = akc.count()
    by_priority, by_method = {}, {}
    for r in m:
        by_priority[r["priority"]] = by_priority.get(r["priority"], 0) + 1
        by_method[r["method"]] = by_method.get(r["method"], 0) + 1
    matched = {r["slug"] for r in m}
    unmatched = sorted((r["slug"], r["akc_name"]) for r in akc.select("slug", "akc_name").collect() if r["slug"] not in matched)
    pages = {}
    for r in m:
        pages.setdefault(r["title"], []).append(r["slug"])

    link_rows = links.filter(F.col("page_id").isin(list({r["page_id"] for r in m}))) if m else links.limit(0)
    lstats = link_rows.agg(
        F.count("*").alias("health_links"), F.countDistinct("resolved").alias("distinct_targets"),
        F.sum(F.col("via_redirect").cast("int")).alias("resolved_via_redirect"),
        F.sum(F.col("disease_id").isNotNull().cast("int")).alias("links_to_disease_pages"),
        F.countDistinct("disease_id").alias("unique_disease_pages")).first().asDict()
    all_diseases = links.filter(F.col("disease_id").isNotNull()).select("disease_id").distinct().count()
    top = (link_rows.filter(F.col("disease_id").isNotNull()).dropDuplicates(["page_id", "disease_id"])
           .groupBy("resolved").count().orderBy(F.col("count").desc(), "resolved").limit(15).collect())

    recs = [json.loads(r.value) for r in spark.read.text(joined_path).collect()]
    joined = [r for r in recs if r["wiki"]]
    coverage = {a: sum(1 for r in joined if r["wiki"].get(a) not in (None, "", [], {})) for a in ATTRIBUTES}
    checks = {"life_study_in_akc_range_pm1": [0, 0], "weight_overlap_10pct": [0, 0], "height_overlap_10pct": [0, 0]}
    disagreements = []
    for r in joined:
        w = r["wiki"]
        tests = {
            "life_study_in_akc_range_pm1": None if r["life_min"] is None or w["life_expectancy_study"] is None
            else r["life_min"] - 1 <= w["life_expectancy_study"] <= r["life_max"] + 1,
            "weight_overlap_10pct": overlap(r["weight_min_kg"], r["weight_max_kg"], w["weight_min_kg"], w["weight_max_kg"], 0.1),
            "height_overlap_10pct": overlap(r["height_min_cm"], r["height_max_cm"], w["height_min_cm"], w["height_max_cm"], 0.1),
        }
        for k, ok in tests.items():
            if ok is not None:
                checks[k][1] += 1
                checks[k][0] += int(ok)
                if not ok:
                    disagreements.append((r["slug"], w["title"], k))
    url_checked = [r for r in m if r["priority"] == 0]
    name_based = {r["slug"]: r["page_id"] for r in name_only.collect()}
    name_vs_url = {"pairs_with_akc_url": len(url_checked),
                   "name_keys_agree": sum(1 for r in url_checked if name_based.get(r["slug"]) == r["page_id"]),
                   "name_keys_disagree": sorted(r["slug"] for r in url_checked
                                                if name_based.get(r["slug"]) not in (None, r["page_id"])),
                   "name_keys_none": sorted(r["slug"] for r in url_checked if r["slug"] not in name_based)}
    random.seed(11)
    sample = random.sample(sorted((r["slug"], r["title"], r["method"]) for r in m), min(30, len(m)))
    return {
        "akc_breeds": n_akc, "matched": len(m), "unmatched": len(unmatched),
        "by_priority": dict(sorted(by_priority.items())), "by_method": dict(sorted(by_method.items(), key=lambda kv: -kv[1])),
        "ambiguous": sorted((r["slug"], r["title"], [a["title"] for a in r["alternatives"] or []][:3]) for r in m if r["ambiguous"]),
        "unique_wiki_breed_pages": len(pages),
        "pages_with_several_akc_breeds": {t: s for t, s in sorted(pages.items()) if len(s) > 1},
        "unmatched_breeds": unmatched,
        "wiki_breed_pages_total": wiki_breeds.count(), "wiki_disease_pages_total": diseases.count(),
        "disease_links_of_joined_breeds": lstats,
        "disease_pages_linked_from_any_wiki_breed": all_diseases,
        "unique_wiki_pages_joined": len(pages) + (lstats["unique_disease_pages"] or 0),
        "top_diseases": [(r["resolved"], r["count"]) for r in top],
        "attribute_coverage_of_joined_breeds": coverage,
        "consistency_checks_agree_of_comparable": {k: f"{a}/{b}" for k, (a, b) in checks.items()},
        "consistency_disagreements": sorted(disagreements),
        "name_keys_vs_akc_url": name_vs_url,
        "manual_check_sample": sample,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF job 3: AKC x Wikipedia join")
    ap.add_argument("--akc", default=str(AKC_DIR))
    ap.add_argument("--wiki", default=str(WIKI_DIR))
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args(argv)
    spark = get_spark("vinf-join")
    stats = run(spark, args.akc, args.wiki, args.out)
    print(json.dumps({k: v for k, v in stats.items() if k not in ("manual_check_sample",)}, indent=2, ensure_ascii=False))
    spark.stop()


if __name__ == "__main__":
    main()
