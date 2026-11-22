"""Query planner and record -> field mapping of the Lucene index (pure Python, no PyLucene needed)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from luceneindex.documents import (article_fields, breed_fields, disease_fields, list_fields, pick_range,  # noqa: E402
                                   wiki_breed_fields)
from luceneindex.plan import facet_clause, numeric_constraints, parse, satisfies  # noqa: E402


def akc_record(**over):
    rec = {"url": "https://www.akc.org/dog-breeds/beagle/", "slug": "beagle", "name": "Beagle", "nicknames": [],
           "group": "Hound Group", "origin": "England", "size": "Small", "temperament": ["merry", "friendly"],
           "health_tests": ["Hip Evaluation"], "colors": ["Tricolor"], "height_display": "13-15 inches",
           "weight_display": "under 20 pounds", "life_min": 10, "life_max": 15, "popularity_rank": 8,
           "year_recognized": 1885, "height_min_cm": 33.0, "height_max_cm": 38.1, "weight_min_kg": 5.9,
           "weight_max_kg": 6.8, "text_blurb": "A merry hound.", "text_about": "About.", "text_health": "Healthy.",
           "text_grooming": "Sheds.", "text_exercise": "Walks.", "text_training": "Food.", "text_nutrition": "Kibble.",
           "text_history": "Old breed.", "did_you_know": ["Snoopy"], "standard": [{"title": "Head", "text": "Domed."}],
           "traits": {"shedding_level": 3, "energy_level": 4, "good_with_young_children": 5, "barking_level": 0,
                      "coat_type": ["Smooth"], "coat_length": ["Short"]},
           "wiki": None}
    rec.update(over)
    return rec


WIKI = {"page_id": 4368, "title": "Beagle", "url": "https://en.wikipedia.org/wiki/Beagle", "names": ["Beagle"],
        "altnames": ["English Beagle"], "nicknames": [], "country": ["England"], "origin_countries": ["England"],
        "fci_number": 161, "fci_group": 6, "registries": ["FCI", "The Kennel Club"], "height_min_cm": 33.0,
        "height_max_cm": 40.0, "weight_min_kg": 9.0, "weight_max_kg": 11.0, "life_expectancy_study": 12.5,
        "lead": "The beagle is a scent hound.", "temperament": "Even-tempered.", "health": "Epilepsy.",
        "history": "Medieval.", "appearance": "Smooth coat.", "coat": "Short", "colour": "Tricolour", "extinct": False,
        "diseases": [{"title": "Canine hip dysplasia", "url": "u"}]}


@pytest.mark.parametrize("query,labels", [
    ("small dog under 10 kg that lives over 14 years", ["size:small | size:xsmall", "weight <= 10 kg", "life >= 14 y"]),
    ("dog breeds from slovakia", ["origin:slovakia"]),
    ("fci group 1 herding dog", ["group:herding", "fci_group=1"]),
    ("large dog between 30 and 40 kg", ["size:large | size:xlarge", "weight 30-40 kg"]),
    ("dog under 20 lbs", ["weight <= 9.1 kg"]),
    ("taller than 24 inches", ["height >= 61 cm"]),
    ("puppy training from 2024", []),
])
def test_constraint_labels(query, labels):
    assert [c["label"] for c in parse(query)["constraints"]] == labels


def test_facet_tokens_become_field_clauses():
    assert facet_clause("shedding_low") == ("shedding", ("range", "shedding", 1, 2))
    assert facet_clause("children_high") == ("children", ("range", "children", 4, 5))
    assert facet_clause("fci_group_10") == ("fci_group", ("range", "fci_group", 10, 10))
    assert facet_clause("origin_czech_republic") == ("origin", ("term", "origin", "czech_republic"))
    assert facet_clause("lifespan_long") == ("life", ("range", "life_max", 14, None))
    assert facet_clause("origin_2024") == (None, None)


def test_long_life_also_accepts_the_measured_life_expectancy():
    c = parse("long-lived dog")["constraints"][0]
    assert c["clauses"] == [("range", "life_max", 14, None), ("range", "life_study", 14.0, None)]
    assert satisfies(c, {"life_max": 12, "life_study": 14.2}) and not satisfies(c, {"life_max": 12})


def test_numeric_spans_leave_the_text_and_between_needs_both_ends():
    constraints, rest = numeric_constraints("a dog between 10 and 20 kg for me")
    assert rest.split() == ["a", "dog", "for", "me"]
    c = constraints[0]
    assert c["op"] == "and"
    assert satisfies(c, {"weight_min_kg": 15.0, "weight_max_kg": 25.0})
    assert not satisfies(c, {"weight_min_kg": 22.0, "weight_max_kg": 30.0})


def test_quoted_phrases_exclusions_and_extinct():
    p = parse('"separation anxiety" puppy -poodle -toy extinct')
    assert p["phrases"] == ["separation anxiety"]
    assert p["exclude"] == ["poodle", "toy"]
    assert p["text"] == "puppy extinct"
    assert p["extinct"] and p["constraints"] == []   # "-toy" is no size constraint


def test_pick_range_prefers_the_wiki_when_the_sources_disagree():
    assert pick_range((5.9, 6.8), (9.0, 11.0)) == (9.0, 11.0)   # AKC Beagle weight = height in inches
    assert pick_range((24.9, 34.0), (25.0, 32.0)) == (24.9, 34.0)
    assert pick_range(None, (9.0, 11.0)) == (9.0, 11.0)


def test_breed_fields_without_wiki():
    d = breed_fields(akc_record())
    assert d["id"] == "breed:beagle" and d["type"] == "breed" and d["text"]["names"] == ["Beagle"]
    assert d["keyword"]["group"] == ["hound"] and d["keyword"]["size"] == ["small"]
    assert d["keyword"]["coat_type"] == ["smooth"] and d["keyword"]["registry"] == ["akc"]
    assert d["int"] == {"shedding": 3, "energy": 4, "children": 5, "life_min": 10, "life_max": 15,
                        "popularity": 8, "year": 1885}   # barking 0 = not recognised
    assert d["double"]["weight_max_kg"] == 6.8 and "Domed." in d["text"]["appearance"]


def test_breed_fields_with_wiki():
    d = breed_fields(akc_record(wiki=WIKI))
    assert d["text"]["names"] == ["Beagle", "English Beagle"]
    assert d["keyword"]["origin"] == ["england"]
    assert d["keyword"]["registry"] == ["fci", "the_kennel_club", "akc"]
    assert d["keyword"]["disease"] == ["canine_hip_dysplasia"]
    assert d["int"]["fci_group"] == 6 and d["double"]["life_study"] == 12.5
    assert (d["double"]["weight_min_kg"], d["double"]["weight_max_kg"]) == (9.0, 11.0)
    assert (d["double"]["height_min_cm"], d["double"]["height_max_cm"]) == (33.0, 38.1)
    assert "Canine hip dysplasia" in d["text"]["health"] and "scent hound" in d["text"]["summary"]


def test_wiki_breed_disease_article_and_list_fields():
    w = wiki_breed_fields(dict(WIKI, page_id=1, title="Tatra Hound", names=[], altnames=["Slovenský kopov"],
                               extinct=True, fci_number=None, registries=[]))
    assert w["id"] == "wiki-breed:1" and w["keyword"]["extinct"] == ["true"] and "registry" not in w["keyword"]
    d = disease_fields({"page_id": 7, "title": "Canine hip dysplasia", "url": "u", "synonyms": ["CHD"], "lead": "Hips.",
                        "akc_breeds": ["Beagle"], "wiki_breeds": ["Beagle", "Tatra Hound"], "specialty": ""})
    assert d["text"]["names"] == ["Canine hip dysplasia", "CHD"] and d["text"]["breeds"] == ["Beagle", "Tatra Hound"]
    a = article_fields({"slug": "s", "title": "T", "url": "u", "description": "D", "text": "Body", "category": "health",
                        "tags": ["Dog Health"], "author": "Jane Doe", "published": "2024-03-05T10:00"})
    assert a["int"]["published"] == 20240305 and a["keyword"]["tag"] == ["dog_health"]
    assert a["keyword"]["author"] == ["jane_doe"]
    lst = list_fields({"slug": "l", "title": "L", "url": "u", "description": "", "text": "x",
                       "breeds": ["beagle", "unknown"]}, {"beagle": "Beagle"})
    assert lst["text"]["breeds"] == ["Beagle"] and lst["keyword"]["breed"] == ["beagle", "unknown"]
