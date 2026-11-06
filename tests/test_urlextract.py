"""Regex URL extractor."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crawler.urlextract import extract_links, extract_sitemap, normalize, same_site  # noqa: E402

BASE = "https://www.akc.org/dog-breeds/golden-retriever/"


def test_absolute_relative_and_single_quotes():
    html = ('<a href="https://www.akc.org/dog-breeds/">hub</a>'
            "<a class='x' href='/dog-breeds/poodle-standard/'>rel</a>"
            '<A HREF="../labrador-retriever/">up</A>')
    assert extract_links(html, BASE) == [
        "https://www.akc.org/dog-breeds/",
        "https://www.akc.org/dog-breeds/poodle-standard/",
        "https://www.akc.org/dog-breeds/labrador-retriever/",
    ]


def test_fragment_tracking_and_entities_are_stripped():
    html = '<a href="/dog-breeds/pug/?utm_source=x&amp;page=2#health">pug</a>'
    assert extract_links(html, BASE) == ["https://www.akc.org/dog-breeds/pug/?page=2"]


def test_non_http_links_are_ignored():
    html = '<a href="mailto:a@b.c">m</a><a href="javascript:void(0)">j</a><a href="tel:123">t</a>'
    assert extract_links(html, BASE) == []


def test_href_not_inside_anchor_is_ignored():
    html = '<link rel="stylesheet" href="/style.css"><a href="/dog-breeds/akita/">a</a>'
    assert extract_links(html, BASE) == ["https://www.akc.org/dog-breeds/akita/"]


def test_normalize_host_case_and_default_port():
    assert normalize("HTTPS://WWW.AKC.ORG:443/Dog-Breeds/Pug/") == "https://www.akc.org/Dog-Breeds/Pug/"


def test_sitemap_and_sitemap_index():
    sm = "<urlset><url><loc> https://www.akc.org/dog-breeds/pug/ </loc></url></urlset>"
    assert extract_sitemap(sm) == ([], ["https://www.akc.org/dog-breeds/pug/"])
    idx = "<sitemapindex><sitemap><loc>https://www.akc.org/article-sitemap1.xml</loc></sitemap></sitemapindex>"
    assert extract_sitemap(idx) == (["https://www.akc.org/article-sitemap1.xml"], [])


def test_same_site():
    assert same_site("https://www.akc.org/dog-breeds/", "www.akc.org")
    assert not same_site("https://akc.org/dog-breeds/", "www.akc.org")


def test_malformed_port_is_skipped_not_raised():
    # seen on akc.org: a DOI written as a URL, which urlsplit() reports as an invalid port
    html = '<a href="https://doi.org:10.18632/oncotarget.1">doi</a><a href="/dog-breeds/pug/">ok</a>'
    assert extract_links(html, BASE) == ["https://www.akc.org/dog-breeds/pug/"]
    assert normalize("https://doi.org:10.18632/x") is None
    assert extract_sitemap("<urlset><url><loc>https://x.org:abc/</loc></url></urlset>") == ([], [])
