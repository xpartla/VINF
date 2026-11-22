"""The three Spark jobs on a local session: job 1 equals the part-1 extractor on the AKC fixtures (incl. an alias
copy), jobs 2+3 on a small bz2 dump built from wikitext snippets. Skipped without Java or PySpark."""
import bz2
import gzip
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("pyspark")
if not (shutil.which("java") or os.environ.get("JAVA_HOME")):
    pytest.skip("no Java runtime", allow_module_level=True)

from extractor.run import canonical_of, extract  # noqa: E402
from indexer.documents import read_jsonl  # noqa: E402
from sparkjobs import akc_extract, join, wiki_extract  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "akc"
AKC = "https://www.akc.org/"
pytestmark = pytest.mark.filterwarnings("ignore:PySpark does not yet fully support pandas")


@pytest.fixture(scope="module")
def spark():
    os.environ.setdefault("VINF_SPARK_MASTER", "local[2]")
    os.environ.setdefault("VINF_SPARK_DRIVER_MEMORY", "1g")
    from sparkjobs.session import get_spark

    s = get_spark("vinf-tests")
    yield s
    s.stop()


def fixture_pages():
    for kind, prefix in (("breeds", "dog-breeds/"), ("pages", "dog-breeds/"), ("articles", None)):
        for f in sorted((FIX / kind).glob("*.html.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                html_text = fh.read()
            slug = f.name[:-len(".html.gz")]
            url = canonical_of(html_text, {"url": "", "final_url": ""}) or f"{AKC}{prefix}{slug}/"
            yield url, html_text


def write_crawl(root, pages):
    meta = root / "meta"
    meta.mkdir(parents=True)
    with open(meta / "akc.jsonl", "w", encoding="utf-8") as m:
        for i, (url, html_text) in enumerate(pages):
            sha = hashlib.sha1((url + str(i)).encode()).hexdigest()
            path = root / "raw" / "akc" / sha[:2] / f"{sha}.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html_text, encoding="utf-8")
            m.write(json.dumps({"url": url, "final_url": url, "status": 200, "content_type": "text/html",
                                "encoding": "utf-8", "file": f"raw/akc/{sha[:2]}/{sha}.html",
                                "fetched_at": f"2026-10-25T10:{i // 60:02d}:{i % 60:02d}Z"}) + "\n")


@pytest.fixture(scope="module")
def akc_out(spark, tmp_path_factory):
    root = tmp_path_factory.mktemp("crawl")
    pages = list(fixture_pages())
    golden = next(h for u, h in pages if u.endswith("/golden-retriever/"))
    write_crawl(root, pages + [(AKC + "dog-breeds/old-golden-slug/", golden)])   # alias copy, same canonical
    out = tmp_path_factory.mktemp("akc")
    summary = akc_extract.run(spark, str(root), str(out))
    return pages, out, summary


def test_akc_job_equals_the_part1_extractor(akc_out):
    pages, out, summary = akc_out
    expected = {}
    for url, html_text in pages:
        kind, rec = extract(html_text, canonical_of(html_text, {"url": url, "final_url": url}))
        expected.setdefault(kind, {})[rec["url"]] = json.loads(json.dumps(rec))   # int dict keys -> str, as in the files
    for kind, name in akc_extract.OUT_NAMES.items():
        got = {r["url"]: r for r in read_jsonl(out / name)}
        assert got == expected.get(kind, {}), kind
    assert summary["alias_pages"] == 1 and summary["breeds"] == len(expected["breed"])


DUMP_PAGES = [
    ("Golden Retriever", 1, None, """{{Infobox dog breed
| name = Golden Retriever
| country = [[Scotland]]
| weight = {{cvt|55|–|75|lb|kg}}
| fcistd = http://www.fci.be/Nomenclature/Standards/111g08-en.pdf
}}
The '''Golden Retriever''' is a [[retriever]].
== Health ==
Prone to [[Hip dysplasia (canine)|hip dysplasia]] and [[cancer]].
[[Category:Dog breeds originating in Scotland]]"""),
    ("Golden retrievers", 2, "Golden Retriever", "#REDIRECT [[Golden Retriever]]"),
    ("Canine hip dysplasia", 3, None, """'''Canine hip dysplasia''' is a malformation of the hip.
[[Category:Dog musculoskeletal disorders]]"""),
    ("Hip dysplasia (canine)", 4, "Canine hip dysplasia", "#REDIRECT [[Canine hip dysplasia]]"),
    ("Cancer", 5, None, "'''Cancer''' is a disease. [[Category:Oncology]]"),
    ("Kromfohrländer", 6, None, "{{Infobox dog breed|name=Kromfohrländer|country=[[Germany]]}} A dog. "
                                "[[Category:Dog breeds originating in Germany]]"),
    ("Dog breed", 7, None, "A '''dog breed''' is a type of dog. [[Category:Dog breeds]]"),
]


def dump_xml(pages):
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    out = ['<mediawiki xml:lang="en">\n  <siteinfo><sitename>Wikipedia</sitename></siteinfo>\n']
    for title, pid, redirect, text in pages:
        red = f'    <redirect title="{esc(redirect)}" />\n' if redirect else ""
        out.append(f"  <page>\n    <title>{esc(title)}</title>\n    <ns>0</ns>\n    <id>{pid}</id>\n{red}"
                   f"    <revision><id>{pid}0</id><text bytes=\"{len(text)}\" xml:space=\"preserve\">{esc(text)}</text>"
                   f"</revision>\n  </page>\n")
    out.append("</mediawiki>\n")
    return "".join(out)


@pytest.fixture(scope="module")
def wiki_out(spark, akc_out, tmp_path_factory):
    d = tmp_path_factory.mktemp("dump")
    (d / "enwiki-test.xml.bz2").write_bytes(bz2.compress(dump_xml(DUMP_PAGES).encode("utf-8")))
    out = tmp_path_factory.mktemp("wiki")
    scan = wiki_extract.scan(spark, str(d / "*.bz2"), str(out))
    parse = wiki_extract.parse(spark, str(out))
    joined = tmp_path_factory.mktemp("joined")
    stats = join.run(spark, str(akc_out[1]), str(out), str(joined))
    return scan, parse, out, joined, stats


def test_wiki_scan_counts_pages_and_selects_dog_articles(wiki_out):
    scan, parse, _, _, _ = wiki_out
    assert (scan["pages"], scan["ns0_redirects"], scan["selected_articles"]) == (7, 2, 4)
    assert parse["by_kind"] == {"breed": 2, "disease": 1, "other": 1}


def test_wiki_parse_writes_breeds_diseases_and_redirects(spark, wiki_out):
    _, _, out, _, _ = wiki_out
    breeds = {r["title"]: r for r in read_jsonl(out / "breeds")}
    assert breeds["Golden Retriever"]["fci_number"] == 111 and breeds["Golden Retriever"]["country"] == ["Scotland"]
    assert breeds["Kromfohrländer"]["country"] == ["Germany"]
    redirects = {r["title"]: r["target"] for r in spark.read.parquet(str(out / "redirects")).collect()}
    assert redirects == {"Golden retrievers": "Golden Retriever", "Hip dysplasia (canine)": "Canine hip dysplasia"}


def test_join_matches_by_title_and_links_diseases_through_redirects(wiki_out):
    *_, joined, stats = wiki_out
    recs = {r["slug"]: r for r in read_jsonl(joined / "breeds")}
    w = recs["golden-retriever"]["wiki"]
    assert w["title"] == "Golden Retriever" and w["match"]["method"] == "name|title"
    assert w["diseases"] == [{"title": "Canine hip dysplasia", "url": "https://en.wikipedia.org/wiki/Canine_hip_dysplasia"}]
    assert recs["beagle"]["wiki"] is None
    assert stats["unique_wiki_pages_joined"] == 2
    assert stats["disease_links_of_joined_breeds"]["resolved_via_redirect"] == 1
    assert [r["title"] for r in read_jsonl(joined / "wiki_only_breeds")] == ["Kromfohrländer"]
    assert [r["akc_breeds"] for r in read_jsonl(joined / "diseases")] == [["Golden Retriever"]]
