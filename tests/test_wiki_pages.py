"""Page parser on 25 real enwiki-20261001 pages; expected values read off the raw infobox by hand (in/lb converted)."""
import gzip
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiki.page import parse_page  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "wiki" / "pages.jsonl.gz"
with gzip.open(FIX, "rt", encoding="utf-8") as _f:
    PAGES = {p["title"]: p for p in map(json.loads, _f)}
PARSED = {}

# title: (country, height cm, weight kg, (fci number, group), origin categories)
EXPECTED = {
    "Golden Retriever": (["Scotland"], (50.8, 61.0), (24.9, 34.0), (111, 8), ["Scotland"]),
    "German Shepherd": (["Germany"], (55.0, 65.0), (22.0, 40.0), (166, 1), ["Germany"]),
    "Poodle": (["Germany", "France"], (24.0, 62.0), (2.0, 32.0), (172, 9), ["France", "Germany"]),
    "Chihuahua (dog breed)": (["Mexico"], (8.0, 23.0), (1.0, 3.0), (218, 9), ["Indigenous Americans", "Mexico"]),
    "Czechoslovakian Wolfdog": (["Czech Republic", "Slovakia"], (60.0, 65.0), (20.0, 26.0), (332, 1),
                                ["Czech Republic", "Slovakia"]),
    "Slovak Cuvac": ([], (59.0, 70.0), (31.0, 44.0), (142, None), ["Slovakia"]),
    "Slovak Rough-haired Pointer": (["Slovakia"], (None, None), (None, None), (320, 7), ["Slovakia"]),
    "Slovenský kopov": (["Slovakia"], (None, None), (None, None), (244, 6), ["Slovakia"]),
    "Siberian Husky": (["Siberia"], (50.8, 59.7), (15.9, 27.2), (270, 5), []),
    "Beagle": (["England"], (33.0, 40.6), (9.1, 11.3), (161, 6), ["England"]),
    "Basenji": (["Democratic Republic of the Congo"], (40.0, 43.0), (9.5, 11.0), (43, 5),
                ["Africa", "Democratic Republic of the Congo"]),
    "Bernese Mountain Dog": (["Switzerland"], (58.0, 70.0), (34.0, 55.0), (45, 2), ["Switzerland"]),
    "Labrador Retriever": (["United Kingdom"], (54.0, 57.0), (24.9, 36.3), (122, 8), ["England"]),
    "Leonberger": (["Germany"], (65.0, 80.0), (None, None), (145, 2), ["Germany"]),
    "Great Dane": (["Germany"], (72.0, 90.0), (None, None), (235, 2), ["Germany"]),
    "Komondor": (["Hungary"], (None, None), (None, None), (53, 1), ["Hungary"]),
    "Collie": (["Scotland", "Northern England"], (None, None), (21.8, 31.8), (None, None), []),
}
NAMES = {
    "Slovak Cuvac": (["Slovak Cuvac", "Slovenský čuvač"], ["Slovak Cuvac", "Slovak Chuvach", "Tatransky Cuvac",
                                                          "Slovak tschuvatsch"], []),
    "Slovenský kopov": (["Slovenský kopov", "Slovak Hound"], ["Slovak Hound", "Black Forest Hound"], []),
    "Czechoslovakian Wolfdog": (["Czechoslovakian Wolfdog"], ["Czechoslovakian Vlciak"], []),
    "Siberian Husky": (["Siberian Husky"], ["Chukcha"], ["Husky", "Sibe"]),
    "Komondor": (["Komondor"], ["Hungarian Commonmop", "Hungarian Sheepdog", "Mop Dog"], []),
    "Xoloitzcuintle": (["Xoloitzcuintle"], ["Xoloitzcuintle", "Xoloitzquintle", "Xoloitzcuintli"], ["Xolo"]),
    "Slovak Rough-haired Pointer": (["Slovak Rough-haired Pointer"], ["Slovensky Hrubosrsky Stavac (Ohar)",
                                                                     "Slovenský hrubosrstý Stavač",
                                                                     "Slovenský Ohař Hrubosrstý"], []),
}


def parsed(title):
    if title not in PARSED:
        p = PAGES[title]
        PARSED[title] = parse_page(p["id"], p["title"], p["text"])
    return PARSED[title]


def test_fixture_count():
    assert len(PAGES) == 25


@pytest.mark.parametrize("title", sorted(EXPECTED))
def test_breed_infobox_attributes(title):
    kind, rec = parsed(title)
    country, height, weight, fci, origin = EXPECTED[title]
    assert kind == "breed" and rec["has_infobox"]
    assert rec["country"] == country
    assert (rec["height_min_cm"], rec["height_max_cm"]) == height
    assert (rec["weight_min_kg"], rec["weight_max_kg"]) == weight
    assert (rec["fci_number"], rec["fci_group"]) == fci
    assert rec["origin_countries"] == origin


@pytest.mark.parametrize("title", sorted(NAMES))
def test_breed_names(title):
    _, rec = parsed(title)
    assert (rec["names"], rec["altnames"], rec["nicknames"]) == NAMES[title]


@pytest.mark.parametrize("title,litter", [("Golden Retriever", (7.2, 7.2)), ("German Shepherd", (6.0, 8.0)),
                                          ("Siberian Husky", (4.0, 8.0)), ("Bernese Mountain Dog", (5.0, 7.0)),
                                          ("Beagle", (None, None))])
def test_litter_size(title, litter):
    _, rec = parsed(title)
    assert (rec["litter_min"], rec["litter_max"]) == litter


@pytest.mark.parametrize("title,years", [("Golden Retriever", 13.2), ("Pug", 7.65), ("Beagle", 12.5),
                                         ("Bernese Mountain Dog", 8.0), ("Komondor", None)])
def test_life_expectancy_from_the_health_section(title, years):
    assert parsed(title)[1]["life_expectancy_study"] == years


def test_sections_are_found_by_heading_and_inherited_by_subsections():
    _, gsd = parsed("German Shepherd")
    assert gsd["section_headings"]["health"] == ["Health", "Lifespan", "Musculoskeletal", "Pituitary dwarfism"]
    assert gsd["section_headings"]["temperament"] == ["Behavior", "Intelligence", "Bite and jaw force"]
    assert "Canine hip dysplasia" in gsd["health_links"] or "Hip dysplasia (canine)" in gsd["health_links"]
    _, wolfdog = parsed("Czechoslovakian Wolfdog")
    assert wolfdog["health"] == "" and wolfdog["health_links"] == []


def test_lead_is_plain_text():
    lead = parsed("Golden Retriever")[1]["lead"]
    assert lead.startswith("The Golden Retriever is a Scottish breed of retriever dog")
    assert not any(c in lead for c in "{}[]<>|")


@pytest.mark.parametrize("title,categories", [("Canine hip dysplasia", ["Dog musculoskeletal disorders"]),
                                              ("Progressive retinal atrophy", ["Dog diseases"]),
                                              ("Cherry eye", ["Dog diseases"])])
def test_disease_pages(title, categories):
    kind, rec = parsed(title)
    assert kind == "disease" and rec["dog_categories"] == categories and rec["lead"]


@pytest.mark.parametrize("title", ["List of dog breeds", "Laika"])
def test_other_dog_pages_are_not_breeds(title):
    assert parsed(title) == ("other", None)
