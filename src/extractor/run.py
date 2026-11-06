"""Extract entities from every stored page into data/extracted/: one record per canonical URL
(akc.org serves copies under old slugs and second categories), category archives counted only."""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import config  # noqa: E402
from extractor.akc_breed import extract_breed  # noqa: E402
from extractor.akc_page import ARTICLE_URL_RE, SITE_SUFFIX_RE, extract_article, extract_list_page  # noqa: E402
from extractor.textutil import body_classes, canonical_url, title  # noqa: E402

OUT_DIR = config.DATA_DIR / "extracted"
SITE_PREFIX = "https://www.akc.org/"
BREED_URL_RE = re.compile(r"^https://www\.akc\.org/dog-breeds/[a-z0-9-]+/$")
HEAD_BYTES = 256 * 1024     # covers <head>; the canonical sits ~120 KB in


def latest_html_pages(meta_dir):
    """{url: meta} of the newest HTML-200 fetch per URL."""
    pages = {}
    for mf in sorted(meta_dir.glob("*.jsonl")):
        for line in mf.read_text(encoding="utf-8").split("\n"):
            if not line.strip():
                continue
            try:
                m = json.loads(line)
            except json.JSONDecodeError:   # a line the crawler is writing right now
                continue
            if m["status"] == 200 and "html" in m["content_type"] and m["file"]:
                pages[m["url"]] = m
    return pages


def read_page(meta, limit=None):
    path = config.DATA_DIR / meta["file"]
    enc = meta.get("encoding") or "utf-8"
    if limit is None:
        return path.read_text(encoding=enc, errors="replace")
    with open(path, "rb") as f:
        return f.read(limit).decode(enc, errors="replace")


def canonical_of(html_text, meta):
    """<link rel=canonical> (https-normalised), else final_url, else url."""
    c = canonical_url(html_text)
    if c.startswith("http://www.akc.org/"):
        c = "https://" + c[len("http://"):]
    return c if c.startswith(SITE_PREFIX) else (meta.get("final_url") or meta["url"])


def classify(html_text, canonical):
    if ARTICLE_URL_RE.match(canonical):
        return "archive" if "archive" in body_classes(html_text) else "article"
    if canonical.startswith(SITE_PREFIX + "dog-breeds/"):
        return "breed-or-list"
    return None


def unique_pages(pages, read=read_page):
    """{canonical: (url, meta)}; the copy fetched under the canonical URL wins, else the first."""
    kept = {}
    for url, meta in sorted(pages.items()):
        head = read(meta, HEAD_BYTES)
        if not canonical_url(head):
            head = read(meta)
        canonical = canonical_of(head, meta)
        prev = kept.get(canonical)
        if prev is None or (url == canonical and prev[0] != canonical):
            kept[canonical] = (url, meta)
    return kept


def extract(html_text, canonical):
    kind = classify(html_text, canonical)
    if kind == "breed-or-list":
        if BREED_URL_RE.match(canonical) and (rec := extract_breed(html_text, canonical)) is not None:
            return "breed", rec
        return "list", extract_list_page(html_text, canonical)
    if kind == "article":
        return "article", extract_article(html_text, canonical)
    if kind == "archive":
        return "archive", {"url": canonical, "title": SITE_SUFFIX_RE.sub("", title(html_text)).strip()}
    return None, None


def coverage(records, skip=("url",)):
    c = Counter()
    for r in records:
        for k, v in r.items():
            if k not in skip and v not in (None, "", [], {}):
                c[k] += 1
    return c


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF regex entity extraction")
    ap.add_argument("--limit", type=int, default=None, help="process at most N pages")
    ap.add_argument("--show", metavar="SLUG", help="print the extracted record of one breed and exit")
    args = ap.parse_args(argv)

    pages = latest_html_pages(config.DATA_DIR / "meta")
    if args.show:
        url = f"https://www.akc.org/dog-breeds/{args.show}/"
        print(json.dumps(extract_breed(read_page(pages[url]), url), indent=2, ensure_ascii=False))
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    kept = unique_pages(pages)
    out = {"breed": [], "article": [], "list": [], "archive": []}
    failed = []
    for i, (canonical, (url, meta)) in enumerate(sorted(kept.items())):
        if args.limit and i >= args.limit:
            break
        kind, rec = extract(read_page(meta), canonical)
        if kind is None:
            failed.append(url)
        else:
            out[kind].append(rec)
    breeds, articles, lists, archives = out["breed"], out["article"], out["list"], out["archive"]

    for name, recs in (("breeds", breeds), ("articles", articles), ("pages", lists), ("archives", archives)):
        with open(OUT_DIR / f"{name}.jsonl", "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {"stored_html_pages": len(pages), "unique_pages": len(kept), "alias_pages": len(pages) - len(kept),
               "breeds": len(breeds), "articles": len(articles), "list_pages": len(lists),
               "archive_pages": len(archives), "unclassified": len(failed), "seconds": round(time.time() - t0, 1)}
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    lines = [f"extracted {len(breeds)} breeds, {len(articles)} articles, {len(lists)} list pages from {len(pages)} stored "
             f"HTML pages in {summary['seconds']}s: {summary['alias_pages']} pages were copies of another page (same "
             f"<link rel=\"canonical\">), {len(archives)} were expert-advice category archives (navigation, not indexed); "
             f"{len(failed)} unclassified"]
    for name, recs in (("breeds", breeds), ("articles", articles), ("pages", lists)):
        if recs:
            lines.append(f"\n[{name}] field coverage (non-empty / {len(recs)}):")
            for k, v in coverage(recs).most_common():
                lines.append(f"  {k:<18}{v:>6}")
    if articles:
        src = Counter(a["body_source"] for a in articles)
        lines.append(f"\narticle body source: {dict(src)}; median words "
                     f"{sorted(a['n_words'] for a in articles)[len(articles) // 2]}")
    report = "\n".join(lines)
    (OUT_DIR / "coverage.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    if failed:
        print("unclassified URLs:", *failed[:10], sep="\n  ")


if __name__ == "__main__":
    main()
