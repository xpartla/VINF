"""Crawl statistics for the report: fetches, bytes, page types, de-duplicated documents, tiktoken tokens."""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import config  # noqa: E402

# (URL regex, relevant?, note)
PAGE_TYPES = [
    ("sitemap", re.compile(r"\.xml$"), False, "seed lists, not content"),
    ("hub+pagination", re.compile(r"^https://www\.akc\.org/dog-breeds/(?:page/\d+/)?$"), False, "navigation only"),
    ("article", re.compile(r"^https://www\.akc\.org/expert-advice/[a-z0-9-]+/[a-z0-9-]+/$"), True, "health/training/breed articles"),
    ("breed", re.compile(r"^https://www\.akc\.org/dog-breeds/[a-z0-9-]+/$"), True, "breed entity pages"),
]
LIST_SLUG_RE = re.compile(r"^https://www\.akc\.org/dog-breeds/(?:sporting|hound|working|terrier|toy|non-sporting|herding|"
                          r"miscellaneous-class|foundation-stock-service|best-.*|.*-dog-breeds|.*-dogs)/$")


def page_type(url):
    if LIST_SLUG_RE.match(url):
        return "group/list", True, "breed lists (membership + text)"
    for name, rx, relevant, note in PAGE_TYPES:
        if rx.search(url):
            return name, relevant, note
    return "other", False, ""


def load_meta(meta_dir):
    rows = defaultdict(list)
    for mf in sorted(meta_dir.glob("*.jsonl")):
        for line in mf.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                rows[mf.stem].append(json.loads(line))
    return rows


def site_table(rows):
    out = []
    for site, ms in rows.items():
        latest = {m["url"]: m for m in ms}                       # last fetch per URL
        statuses = Counter(m["status"] for m in ms)
        html_ok = [m for m in latest.values() if m["status"] == 200 and "html" in m["content_type"]]
        on_disk = sum((config.DATA_DIR / m["file"]).stat().st_size for m in latest.values()
                      if m["file"] and (config.DATA_DIR / m["file"]).exists())
        out.append({"site": site, "fetches": len(ms), "unique_urls": len(latest), "html_200": len(html_ok),
                    "mb_on_disk": on_disk / 1e6, "retries": sum(m["retries"] for m in ms),
                    "avg_ms": sum(m["elapsed_ms"] for m in ms) / max(len(ms), 1),
                    "statuses": dict(sorted(statuses.items()))})
    return out


def type_table(rows):
    agg = {}
    for ms in rows.values():
        latest = {m["url"]: m for m in ms}
        for url, m in latest.items():
            name, relevant, note = page_type(url)
            a = agg.setdefault(name, {"type": name, "pages": 0, "mb": 0.0, "relevant": relevant, "note": note})
            a["pages"] += 1
            a["mb"] += m["size"] / 1e6
    return sorted(agg.values(), key=lambda a: -a["pages"])


def token_table(extracted_dir, raw=False, rows=None):
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    out = []
    text_fields = {"breeds": lambda r: " ".join(str(v) for k, v in r.items() if k.startswith("text_") or k in ("name", "group", "origin")),
                   "articles": lambda r: r["title"] + " " + r["text"],
                   "pages": lambda r: r["title"] + " " + r["text"]}
    for name, getter in text_fields.items():
        path = extracted_dir / f"{name}.jsonl"
        if not path.exists():
            continue
        n = tokens = words = 0
        for line in path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                text = getter(json.loads(line))
                n += 1
                words += len(text.split())
                tokens += len(enc.encode(text, disallowed_special=()))
        out.append({"what": f"extracted text: {name}", "docs": n, "words": words, "tokens": tokens})
    if raw and rows:
        n = tokens = 0
        for ms in rows.values():
            for m in {m["url"]: m for m in ms}.values():
                if m["file"] and (config.DATA_DIR / m["file"]).exists():
                    n += 1
                    tokens += len(enc.encode((config.DATA_DIR / m["file"]).read_text(encoding="utf-8", errors="replace"),
                                             disallowed_special=()))
        out.append({"what": "raw HTML/XML on disk", "docs": n, "words": None, "tokens": tokens})
    return out


def documents_table(extracted_dir):
    """From summary.json written by extractor/run.py."""
    path = extracted_dir / "summary.json"
    if not path.exists():
        return []
    s = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"what": "breed records", "count": s["breeds"], "indexed": "yes"},
        {"what": "articles", "count": s["articles"], "indexed": "yes"},
        {"what": "breed hub / group / list pages", "count": s["list_pages"], "indexed": "yes"},
        {"what": "expert-advice category archives (navigation)", "count": s["archive_pages"], "indexed": "no"},
        {"what": "copies of another page (same canonical URL)", "count": s["alias_pages"], "indexed": "no"},
        {"what": "stored HTML pages", "count": s["stored_html_pages"], "indexed": "-"},
    ]


def print_tables(sites, types, tokens, md, docs=()):
    if md:
        print("| site | fetches | unique URLs | HTML 200 | MB on disk | retries | avg ms | HTTP statuses |\n|---|---|---|---|---|---|---|---|")
        for s in sites:
            print(f"| {s['site']} | {s['fetches']} | {s['unique_urls']} | {s['html_200']} | {s['mb_on_disk']:.1f} | {s['retries']} | {s['avg_ms']:.0f} | {s['statuses']} |")
        print("\n| page type | pages | MB | relevant | note |\n|---|---|---|---|---|")
        for t in types:
            print(f"| {t['type']} | {t['pages']} | {t['mb']:.1f} | {'yes' if t['relevant'] else 'no'} | {t['note']} |")
        rel = [t for t in types if t["relevant"]]
        print(f"| **total** | **{sum(t['pages'] for t in types)}** | **{sum(t['mb'] for t in types):.1f}** | "
              f"**{sum(t['pages'] for t in rel)} pages / {sum(t['mb'] for t in rel):.1f} MB** | |")
        if docs:
            print("\n| documents (one per canonical URL) | count | indexed |\n|---|---|---|")
            for d in docs:
                print(f"| {d['what']} | {d['count']} | {d['indexed']} |")
        if tokens:
            print("\n| text | documents | words | tiktoken tokens (cl100k_base) |\n|---|---|---|---|")
            for t in tokens:
                print(f"| {t['what']} | {t['docs']} | {t['words'] if t['words'] is not None else '-'} | {t['tokens']} |")
        return
    print(f"{'site':<8}{'fetches':>9}{'unique':>8}{'html200':>9}{'MB disk':>9}{'retries':>9}{'avg ms':>8}  statuses")
    for s in sites:
        print(f"{s['site']:<8}{s['fetches']:>9}{s['unique_urls']:>8}{s['html_200']:>9}{s['mb_on_disk']:>9.1f}{s['retries']:>9}{s['avg_ms']:>8.0f}  {s['statuses']}")
    print(f"\n{'page type':<16}{'pages':>7}{'MB':>9}  relevant  note")
    for t in types:
        print(f"{t['type']:<16}{t['pages']:>7}{t['mb']:>9.1f}  {'yes' if t['relevant'] else 'no':<8}  {t['note']}")
    rel = [t for t in types if t["relevant"]]
    print(f"{'total':<16}{sum(t['pages'] for t in types):>7}{sum(t['mb'] for t in types):>9.1f}  relevant: "
          f"{sum(t['pages'] for t in rel)} pages, {sum(t['mb'] for t in rel):.1f} MB")
    if docs:
        print(f"\n{'documents (one per canonical URL)':<48}{'count':>7}  indexed")
        for d in docs:
            print(f"{d['what']:<48}{d['count']:>7}  {d['indexed']}")
    if tokens:
        print(f"\n{'text':<28}{'docs':>7}{'words':>10}{'tokens':>11}")
        for t in tokens:
            print(f"{t['what']:<28}{t['docs']:>7}{(t['words'] if t['words'] is not None else '-'):>10}{t['tokens']:>11}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF crawl statistics")
    ap.add_argument("--tokens", action="store_true", help="count tiktoken tokens of the extracted text")
    ap.add_argument("--raw", action="store_true", help="with --tokens: also tokenize the raw HTML (slow)")
    ap.add_argument("--md", action="store_true", help="markdown output for the wiki")
    args = ap.parse_args(argv)
    rows = load_meta(config.DATA_DIR / "meta")
    tokens = token_table(config.DATA_DIR / "extracted", raw=args.raw, rows=rows) if args.tokens else []
    print_tables(site_table(rows), type_table(rows), tokens, args.md, documents_table(config.DATA_DIR / "extracted"))


if __name__ == "__main__":
    main()
