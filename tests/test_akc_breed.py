"""Breed extractor on 28 real pages; expected_breeds.json comes from an independent json.loads parse (test-time only)."""
import gzip
import html
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from extractor.akc_breed import TRAITS, extract_breed  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "akc"
EXPECTED = json.loads((FIX / "expected_breeds.json").read_text(encoding="utf-8"))
SLUGS = sorted(EXPECTED)
RECORDS = {}


def page(slug):
    with gzip.open(FIX / "breeds" / f"{slug}.html.gz", "rt", encoding="utf-8") as f:
        return f.read()


def record(slug):
    if slug not in RECORDS:
        RECORDS[slug] = extract_breed(page(slug), f"https://www.akc.org/dog-breeds/{slug}/")
    return RECORDS[slug]


def test_fixture_count():
    assert len(SLUGS) >= 20


@pytest.mark.parametrize("slug", SLUGS)
def test_identity_fields(slug):
    rec, exp = record(slug), EXPECTED[slug]
    assert rec is not None and rec["slug"] == slug
    assert rec["name"] == exp["name"]
    assert rec["group"] == exp["group"]
    assert rec["origin"] == exp["origin"]
    assert rec["year_recognized"] == exp["year_recognized"]
    assert rec["url"].endswith(f"/{slug}/")


@pytest.mark.parametrize("slug", SLUGS)
def test_life_expectancy(slug):
    rec, exp = record(slug), EXPECTED[slug]
    assert (rec["life_min"], rec["life_max"]) == (exp["life_min"], exp["life_max"])
    m = re.match(r"(\d+)\s*-\s*(\d+)\s*years", exp["pagemap_life"] or "")
    if m:   # second source of the same fact inside the page
        assert (rec["life_min"], rec["life_max"]) == (int(m.group(1)), int(m.group(2)))


@pytest.mark.parametrize("slug", SLUGS)
def test_height_weight_and_unit_conversion(slug):
    rec, exp = record(slug), EXPECTED[slug]
    assert (rec["height_min_in"], rec["height_max_in"]) == (exp["height_min_in"], exp["height_max_in"])
    assert (rec["weight_min_lb"], rec["weight_max_lb"]) == (exp["weight_min_lb"], exp["weight_max_lb"])
    assert rec["height_display"] == exp["height_display"]
    if rec["height_max_in"] is not None:
        assert rec["height_max_cm"] == pytest.approx(rec["height_max_in"] * 2.54, abs=0.06)
    if rec["weight_max_lb"] is not None:
        assert rec["weight_max_kg"] == pytest.approx(rec["weight_max_lb"] * 0.4536, abs=0.06)


@pytest.mark.parametrize("slug", SLUGS)
def test_size_and_popularity(slug):
    rec, exp = record(slug), EXPECTED[slug]
    assert rec["size"] == exp["size"]
    assert "<" not in rec["size"]
    assert rec["popularity_rank"] == exp["popularity_rank"]


@pytest.mark.parametrize("slug", SLUGS)
def test_temperament_and_traits(slug):
    rec, exp = record(slug), EXPECTED[slug]
    assert rec["temperament"] == exp["temperament"]
    for key, score in exp["traits"].items():
        assert rec["traits"][key] == score
    for key in TRAITS:
        assert isinstance(rec["traits"][key], int) and 1 <= rec["traits"][key] <= 5, key
    assert rec["traits"]["coat_type"] == exp["coat_type"]
    assert rec["traits"]["coat_length"] == exp["coat_length"]


@pytest.mark.parametrize("slug", SLUGS)
def test_health_tests_and_texts(slug):
    rec, exp = record(slug), EXPECTED[slug]
    assert rec["health_tests"] == exp["health_tests"]
    assert rec["text_health"].startswith(exp["text_health_startswith"])
    for key in ("text_about", "text_health", "text_grooming", "text_exercise", "text_training", "text_nutrition", "text_history"):
        assert "<" not in rec[key] and "&quot;" not in rec[key] and "\\/" not in rec[key], key
    assert rec["text_about"] and rec["text_history"]


def test_non_breed_pages_return_none():
    with gzip.open(FIX / "pages" / "herding.html.gz", "rt", encoding="utf-8") as f:
        assert extract_breed(f.read(), "https://www.akc.org/dog-breeds/herding/") is None
    assert extract_breed("<html><body><p>no breed here</p></body></html>") is None
    assert extract_breed("") is None


def _synthetic_page(breed_data, slug="test-dog", pagemap=""):
    props = {"settings": {"current_breed": slug, "breed_data": breed_data}}
    attr = html.escape(json.dumps(props, separators=(",", ":")), quote=True)   # compact, like the real page
    return f'<html>{pagemap}<div data-js-component="breedPage" data-js-props="{attr}"></div></html>'


def test_single_value_life_expectancy_and_missing_fields():
    page_html = _synthetic_page({
        "basics": {"test-dog": {"breed_name": "Test Dog", "breed_group": "Toy Group", "life_expectancy": "7 years",
                                "related_breeds_items": {"other": {"breed_name": "Other", "life_expectancy": "10-12 years"}}}},
        "traits": {"test-dog": {"temperament": "calm / sweet", "traits": {"energy_level": {"selected": [], "score": 2}}}},
    })
    rec = extract_breed(page_html, "https://www.akc.org/dog-breeds/test-dog/")
    assert rec["name"] == "Test Dog" and rec["group"] == "Toy Group"
    assert (rec["life_min"], rec["life_max"]) == (7, 7)          # not the related breed's 10-12
    assert rec["temperament"] == ["calm", "sweet"] and rec["traits"] == {"energy_level": 2}
    assert rec["height_max_in"] is None and rec["size"] == "" and rec["health_tests"] == [] and rec["popularity_rank"] is None


def test_pagemap_comment_is_the_fallback_for_life_expectancy():
    pagemap = '<!-- <PageMap><Attribute name="life_expectancy">Life Expectancy: 12-15 years</Attribute></PageMap> -->'
    page_html = _synthetic_page({"basics": {"test-dog": {"breed_name": "Test Dog", "life_expectancy": ""}}}, pagemap=pagemap)
    rec = extract_breed(page_html, "")
    assert (rec["life_min"], rec["life_max"]) == (12, 15)
