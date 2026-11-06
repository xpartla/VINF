"""Article and list-page extractors on real stored pages."""
import gzip
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extractor.akc_page import NON_BREED_SLUG_RE, extract_article, extract_list_page  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "akc"

# read off the fixture pages by hand
ARTICLES = {
    "5-surprising-signs-your-pet-might-need-to-see-a-vet": dict(
        category="health", title="5 Surprising Signs Your Pet Might Need to See a Vet", published="2009-01-01",
        author="AKC Staff", body_source="body", min_words=400, max_words=700, starts="Our pets can't talk",
        tags={"Health", "Help & Advice"}),
    "dogfights-the-dos-and-donts": dict(   # canonical URL differs from the crawled one
        category="training", title="How to Break Up a Dog Fight", published="2021-06-18", modified="2026-03-02",
        author="Stephanie Gibeault, MSc, CPDT", body_source="body", min_words=900, max_words=1300,
        starts="Dog fights are intense, dangerous, and scary.", tags={"Training", "Basic Training"}),
    "why-i-sold-a-puppy-to-miley-cyrus": dict(
        category="news", title="Why I Sold a Puppy to Miley Cyrus", published="2009-01-01", author="AKC Staff",
        body_source="body", min_words=800, max_words=1200, starts="Anyone who follows Miley Cyrus", tags={"Shetland Sheepdog"}),
    # photo post without body text: <main> fallback, no widgets
    "club-spotlight-sturgis-kennel-club": dict(
        category="lifestyle", title="Club Spotlight: Sturgis Kennel Club", published="2013-08-15", author="AKC Staff",
        body_source="main", min_words=0, max_words=20, starts="", tags={"Lifestyle"}),
}


def page(kind, slug):
    with gzip.open(FIX / kind / f"{slug}.html.gz", "rt", encoding="utf-8") as f:
        return f.read()


@pytest.mark.parametrize("slug", sorted(ARTICLES))
def test_article_fields(slug):
    exp = ARTICLES[slug]
    url = f"https://www.akc.org/expert-advice/{exp['category']}/{slug}/"
    a = extract_article(page("articles", slug), url)
    assert a["slug"] == slug and a["category"] == exp["category"] and a["url"] == url
    assert a["title"] == exp["title"]
    assert a["published"] == exp["published"]
    if "modified" in exp:
        assert a["modified"] == exp["modified"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", a["modified"])
    assert a["author"] == exp["author"]
    assert exp["tags"] <= set(a["tags"])
    assert a["body_source"] == exp["body_source"]
    assert exp["min_words"] <= a["n_words"] <= exp["max_words"]
    assert a["text"].startswith(exp["starts"])
    assert a["n_words"] == len(a["text"].split())


@pytest.mark.parametrize("slug", sorted(ARTICLES))
def test_article_text_is_clean(slug):
    a = extract_article(page("articles", slug), f"https://www.akc.org/expert-advice/x/{slug}/")
    for noise in ("Event Search", "Terms of Use", "admin-ajax", "<", "&amp;", "&nbsp;", "DOWNLOAD E-BOOK"):
        assert noise not in a["text"], noise


@pytest.mark.parametrize("slug,title,member,has_description", [("best-family-dogs", "Best Family Dogs", "beagle", True),
                                                               ("herding", "Herding Group", "australian-shepherd", False)])
def test_list_page(slug, title, member, has_description):
    r = extract_list_page(page("pages", slug), f"https://www.akc.org/dog-breeds/{slug}/")
    assert r["slug"] == slug and r["title"] == title
    assert bool(r["description"]) == has_description
    assert member in r["breeds"] and len(r["breeds"]) >= 10
    assert not any(NON_BREED_SLUG_RE.match(s) for s in r["breeds"])
    assert len(r["breeds"]) == len(set(r["breeds"]))
    assert 100 < r["n_words"] < 800            # the menus, the breed drop-down and the footer are gone
    assert "Event Search" not in r["text"] and "<" not in r["text"]


def test_non_breed_slug_filter():
    assert NON_BREED_SLUG_RE.match("best-family-dogs") and NON_BREED_SLUG_RE.match("smallest-dog-breeds")
    assert NON_BREED_SLUG_RE.match("herding") and NON_BREED_SLUG_RE.match("page")
    assert not NON_BREED_SLUG_RE.match("bernese-mountain-dog") and not NON_BREED_SLUG_RE.match("beagle")


def test_article_without_markup():
    a = extract_article("<html><head><title>Bare</title></head><body><p>Just text</p></body></html>",
                        "https://www.akc.org/expert-advice/health/bare/")
    assert a["title"] == "Bare" and a["body_source"] == "page" and a["text"] == "Just text"
    assert a["published"] == "" and a["author"] == "" and a["tags"] == []
