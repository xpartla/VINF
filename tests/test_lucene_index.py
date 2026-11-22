"""Lucene index and searcher on a small in-memory index (skipped without PyLucene; run in the Docker image)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
pytest.importorskip("lucene")

from luceneindex import env  # noqa: E402
from luceneindex.build import write_index  # noqa: E402
from luceneindex.documents import article_fields, breed_fields, disease_fields, wiki_breed_fields  # noqa: E402
from luceneindex.searcher import LuceneSearcher  # noqa: E402
from test_lucene_plan import WIKI, akc_record  # noqa: E402


def breed(slug, name, shedding, size, kg, life_max, origin="Germany", **over):
    return breed_fields(akc_record(
        slug=slug, name=name, url=f"https://www.akc.org/dog-breeds/{slug}/", size=size, origin=origin,
        weight_min_kg=kg[0], weight_max_kg=kg[1], life_max=life_max,
        traits={"shedding_level": shedding, "good_with_young_children": 5}, **over))


DOCS = [
    breed("rottweiler", "Rottweiler", 3, "Large", (36.0, 61.0), 10, temperament=["loyal", "guardian"],
          text_health="Hip dysplasia is common.", nicknames=["Rottie"]),
    breed("bichon-frise", "Bichon Frise", 1, "Small", (5.0, 8.0), 15, origin="France",
          text_blurb="A cheerful hypoallergenic companion."),
    breed("poodle-toy", "Poodle (Toy)", 1, "XSmall", (2.0, 3.0), 18, origin="France"),
    breed("german-shepherd-dog", "German Shepherd Dog", 4, "Large", (22.0, 40.0), 14,
          wiki=dict(WIKI, title="German Shepherd", names=["German Shepherd"],
                    altnames=["Alsatian", "Deutscher Schäferhund", "Berger Allemand", "Schäfer", "GSD"])),
    breed("slovensky-cuvac", "Slovensky Cuvac", 3, "Large", (31.0, 44.0), 13, origin="Slovakia"),
    wiki_breed_fields(dict(WIKI, page_id=11, title="Tatra Hound", names=[], altnames=[], origin_countries=["Slovakia"],
                           country=["Slovakia"], diseases=[])),
    wiki_breed_fields(dict(WIKI, page_id=12, title="Old Slovak Terrier", names=[], altnames=[], extinct=True,
                           origin_countries=["Slovakia"], country=[], diseases=[])),
    disease_fields({"page_id": 7, "title": "Canine hip dysplasia", "url": "u", "synonyms": [],
                    "lead": "Hip dysplasia is a malformation of the hip joint.", "akc_breeds": ["Rottweiler"],
                    "wiki_breeds": [], "specialty": ""}),
    article_fields({"slug": "anxiety", "title": "Separation Anxiety in Puppies", "url": "u", "category": "training",
                    "description": "When a puppy is left alone.", "text": "Separation anxiety starts early.",
                    "tags": [], "author": "A", "published": "2025-01-02"}),
    article_fields({"slug": "anxious", "title": "Anxiety and separation", "url": "u", "category": "training",
                    "description": "Words apart.", "text": "Anxiety is not the same as separation.", "tags": [],
                    "author": "A", "published": "2021-06-01"}),
]


@pytest.fixture(scope="module")
def s():
    env.init()
    from org.apache.lucene.store import ByteBuffersDirectory

    directory = ByteBuffersDirectory()
    write_index(DOCS, directory)
    return LuceneSearcher(directory=directory)


def ids(res):
    return [h["id"] for h in res["hits"]]


def test_index_has_every_document(s):
    assert s.reader.numDocs() == len(DOCS)


def test_analyzers_fold_accents_and_stem_prose(s):
    assert env.analyze(s.analyzers["names"], "Slovenský Čuvač's") == ["slovensky", "cuvac"]
    assert env.analyze(s.analyzers["english"], "The dog sheds and is shedding") == ["dog", "shed", "shed"]


def test_range_constraints_filter_in_strict_mode(s):
    res = s.search("low shedding dog under 10 kg", strict=True)
    assert set(ids(res)) == {"breed:bichon-frise", "breed:poodle-toy"}


def test_soft_constraints_rank_matching_breeds_first(s):
    res = s.search("low shedding dog", k=3)
    assert set(ids(res)[:2]) == {"breed:bichon-frise", "breed:poodle-toy"}
    assert res["total"] > 2   # the others still match, below


def test_origin_term_and_extinct_breeds(s):
    assert set(ids(s.search("dog breeds from slovakia", strict=True))) == {"breed:slovensky-cuvac", "wiki-breed:11"}
    assert "wiki-breed:12" in ids(s.search("extinct dog breeds from slovakia", strict=True))


def test_unknown_keyword_values_are_ignored(s):
    res = s.search("how to stop a puppy from biting", strict=True)
    assert res["ignored"] == ["origin:biting"] and res["total"] > 0


def test_fuzzy_finds_a_misspelled_breed(s):
    res = s.search("rotweiler")
    assert res["misspelled"] == ["rotweiler"] and ids(res)[0] == "breed:rottweiler"
    assert s.fuzzy_expansions("rotweiler") == ["rottweiler"]
    assert s.search("a dog that is with the")["misspelled"] == []   # stop words are not misspellings


def test_quoted_phrase_is_required(s):
    res = s.search('"separation anxiety"')
    assert ids(res) == ["article:anxiety"]   # the other article has both words, not the phrase


def test_exclusion_and_type_filter(s):
    assert "breed:poodle-toy" not in ids(s.search("low shedding dog -poodle"))
    assert "article:anxiety" not in ids(s.search("separation anxiety -puppies"))   # stemmed title: puppi
    assert ids(s.search("hip dysplasia", doc_type="disease")) == ["disease:7"]


def test_alternative_wiki_names_find_the_breed(s):
    assert ids(s.search("deutscher schaferhund"))[0] == "breed:german-shepherd-dog"
    assert ids(s.search("alsatian"))[0] == "breed:german-shepherd-dog"


@pytest.mark.parametrize("query,expected", [
    ("shedding:[1 TO 2]", {"breed:bichon-frise", "breed:poodle-toy"}),
    ("+type:breed +weight_max_kg:[* TO 10]", {"breed:bichon-frise", "breed:poodle-toy"}),
    ("origin:slovakia AND type:breed", {"breed:slovensky-cuvac"}),
    ("names:rotweiler~2", {"breed:rottweiler"}),
    ('"separation anxiety" AND published:[20250101 TO 20251231]', {"article:anxiety"}),
    ("+type:breed -origin:france +life_max:[14 TO *]", {"breed:german-shepherd-dog"}),
    ("names:rott*", {"breed:rottweiler"}),
])
def test_lucene_query_syntax(s, query, expected):
    assert set(ids(s.syntax_search(query))) == expected


def test_sort_by_popularity_and_date(s):
    res = s.syntax_search("type:article", sort="published")
    assert ids(res) == ["article:anxiety", "article:anxious"]


def test_explanation_lists_the_scoring_terms(s):
    res = s.search("rottweiler hip")
    hit = next(h for h in res["hits"] if h["id"] == "breed:rottweiler")
    terms = s.matched_terms(res["query"], hit["doc"])
    assert "names:rottweiler" in terms and "health:hip" in terms
    assert "breeds:rottweiler" in s.matched_terms(res["query"], res["hits"][ids(res).index("disease:7")]["doc"])


def test_classic_similarity_switch(s):
    s.set_similarity("classic")
    try:
        assert ids(s.search("rottweiler"))[0] == "breed:rottweiler"
    finally:
        s.set_similarity("bm25")
