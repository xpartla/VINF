"""Extraction driver: canonical de-duplication and page classification."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extractor.run import canonical_of, classify, extract, unique_pages  # noqa: E402

AKC = "https://www.akc.org/"


def page(canonical, body_class="wp-singular single single-article", title="A page"):
    return (f'<html><head><title>{title} &#8211; American Kennel Club</title>'
            f'<link rel="canonical" href="{canonical}" /></head>'
            f'<body class="{body_class}"><main><div class="content-body__text content-body__text-long"><p>Text.</p>'
            f'</div></main></body></html>')


def test_canonical_of_normalises_scheme_and_falls_back_for_missing_or_foreign_canonicals():
    meta = {"url": AKC + "expert-advice/health/a/", "final_url": AKC + "expert-advice/health/a/"}
    assert canonical_of(page("http://www.akc.org/expert-advice/health/b/"), meta) == AKC + "expert-advice/health/b/"
    assert canonical_of(page("https://www.realtor.com/advice/x/"), meta) == AKC + "expert-advice/health/a/"
    assert canonical_of("<html></html>", {"url": "u", "final_url": "f"}) == "f"
    assert canonical_of("<html></html>", {"url": "u", "final_url": ""}) == "u"


def test_classify_article_archive_breed_section_and_unknown():
    assert classify(page(AKC + "expert-advice/health/a/"), AKC + "expert-advice/health/a/") == "article"
    assert classify(page(AKC + "expert-advice/training/trick-dog/", "archive category"),
                    AKC + "expert-advice/training/trick-dog/") == "archive"
    assert classify(page(AKC + "dog-breeds/pug/"), AKC + "dog-breeds/pug/") == "breed-or-list"
    assert classify(page(AKC + "dog-breeds/"), AKC + "dog-breeds/") == "breed-or-list"
    assert classify(page(AKC + "sports/agility/"), AKC + "sports/agility/") is None


def test_unique_pages_keeps_one_copy_per_canonical_and_prefers_the_canonical_url():
    canon = AKC + "dog-breeds/st-bernard/"
    urls = [AKC + "dog-breeds/saint-bernard/", canon, AKC + "dog-breeds/zz-old-st-bernard/", AKC + "dog-breeds/pug/"]
    pages = {u: {"url": u, "final_url": canon if "bernard" in u else u} for u in urls}
    read = lambda meta, limit=None: page(canon, "single single-breed") if "bernard" in meta["url"] else page(AKC + "dog-breeds/pug/")
    kept = unique_pages(pages, read=read)
    assert set(kept) == {canon, AKC + "dog-breeds/pug/"}
    assert kept[canon][0] == canon           # saint-bernard (sorted first) was replaced, zz-old-st-bernard skipped


def test_unique_pages_without_a_copy_under_the_canonical_url_keeps_the_first():
    canon = AKC + "expert-advice/health/c/"
    pages = {AKC + "expert-advice/health/b/": {"url": AKC + "expert-advice/health/b/", "final_url": canon},
             AKC + "expert-advice/health/a/": {"url": AKC + "expert-advice/health/a/", "final_url": canon}}
    kept = unique_pages(pages, read=lambda meta, limit=None: page(canon))
    assert list(kept) == [canon] and kept[canon][0] == AKC + "expert-advice/health/a/"


def test_extract_dispatches_on_kind():
    kind, rec = extract(page(AKC + "expert-advice/health/a/", title="Hip Dysplasia"), AKC + "expert-advice/health/a/")
    assert (kind, rec["title"], rec["category"], rec["text"]) == ("article", "Hip Dysplasia", "health", "Text.")
    kind, rec = extract(page(AKC + "expert-advice/training/trick-dog/", "archive", title="Trick Dog Archives"),
                        AKC + "expert-advice/training/trick-dog/")
    assert (kind, rec) == ("archive", {"url": AKC + "expert-advice/training/trick-dog/", "title": "Trick Dog Archives"})
    kind, rec = extract(page(AKC + "dog-breeds/herding/", "archive", title="Herding Group"), AKC + "dog-breeds/herding/")
    assert (kind, rec["slug"], rec["title"]) == ("list", "herding", "Herding Group")
    assert extract("<html></html>", AKC + "sports/") == (None, None)
