"""Tokeniser, TF/IDF formulas, index builder, query expansion, searcher."""
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indexer.build import build_index  # noqa: E402
from indexer.idf import idf_classic, idf_max, idf_none, idf_smooth, tf_binary, tf_log, tf_raw  # noqa: E402
from indexer.query_expand import expand_query  # noqa: E402
from indexer.search import Searcher  # noqa: E402
from indexer.tokenize import tokenize  # noqa: E402

DOCS = [
    {"id": "d0", "type": "breed", "title": "Pug", "url": "u0", "text": "dog dog dog pug small", "facets": ["size_small", "shedding_high"]},
    {"id": "d1", "type": "breed", "title": "Great Dane", "url": "u1", "text": "dog giant", "facets": ["size_xlarge"]},
    {"id": "d2", "type": "article", "title": "Cats", "url": "u2", "text": "cat cat dog", "facets": []},
    {"id": "d3", "type": "article", "title": "Birds", "url": "u3", "text": "bird dog", "facets": []},
]


@pytest.fixture(scope="module")
def index():
    return build_index(DOCS)


def test_tokenize_lowercases_strips_apostrophes_keeps_underscores_and_drops_single_chars():
    assert tokenize("The Dog's coat doesn't shed; a 2-in-1 size_small!") == ["the", "dogs", "coat", "doesnt", "shed", "in", "size_small"]


def test_tf_variants():
    assert tf_raw(3) == 3.0
    assert tf_log(1) == 1.0 and tf_log(3) == pytest.approx(1 + math.log(3))
    assert tf_binary(7) == 1.0 and tf_binary(0) == 0.0


def test_idf_formulas_against_hand_computed_values():
    N, max_df = 4, 4
    assert idf_classic(N, 2) == pytest.approx(math.log(2))
    assert idf_classic(N, 4) == 0.0                         # a term in every document gets 0
    assert idf_smooth(N, 2) == pytest.approx(math.log(5 / 3) + 1)
    assert idf_smooth(N, 4) == pytest.approx(math.log(5 / 5) + 1) == 1.0   # ... but 1 with smoothing
    assert idf_smooth(N, 0) > idf_smooth(N, 1)              # unseen term: no division by zero
    assert idf_max(N, 2, max_df) == pytest.approx(math.log(2))
    assert idf_max(N, 4, max_df) == 0.0
    assert idf_none(N, 1) == idf_none(N, 4) == 1.0


def test_index_statistics(index):
    assert index["N"] == 4
    assert index["df"]["dog"] == 4 and index["max_df"] == 4
    assert index["df"]["cat"] == 1 and index["df"]["size_small"] == 1
    assert dict(index["postings"]["dog"]) == {0: 3, 1: 1, 2: 1, 3: 1}
    assert index["doc_len"] == [7, 3, 3, 2]                 # facets count as tokens
    assert index["docs"][0]["id"] == "d0" and index["docs"][0]["unique_terms"] == 5


def test_norm_is_vector_length(index):
    # doc 0 with raw tf and no idf: tf = {dog:3, pug:1, small:1, size_small:1, shedding_high:1}
    assert index["norms"]["raw:none"][0] == pytest.approx(math.sqrt(9 + 1 + 1 + 1 + 1))
    # doc 2 with raw tf and classic idf: cat df=1 -> log 4, dog df=4 -> 0
    assert index["norms"]["raw:classic"][2] == pytest.approx(math.sqrt((2 * math.log(4)) ** 2))


def test_search_ranking_and_idf_difference(index):
    s = Searcher(index=index)
    top = s.search("cat", tf="raw", idf="classic", k=3)
    assert [d["id"] for _, d, _ in top] == ["d2"]
    # "dog" is in every document: classic idf gives it weight 0 -> no results; smooth idf still ranks
    assert s.search("dog", idf="classic", k=5) == []
    smooth = s.search("dog", tf="raw", idf="smooth", k=5)
    assert len(smooth) == 4
    assert smooth[0][1]["id"] == "d0"                      # tf 3 outweighs the longer vector (cosine)
    # type filter
    assert all(d["type"] == "breed" for _, d, _ in s.search("dog", idf="smooth", doc_type="breed"))


def test_query_expansion_adds_facets_and_searcher_uses_them(index):
    assert expand_query("a small dog that does not shed") == ["shedding_low", "size_small", "size_xsmall"]
    assert expand_query("calm apartment dog") == ["energy_low", "adaptability_high", "barking_low", "size_small", "size_medium"]
    assert expand_query("herding group") == ["group_herding"]
    assert expand_query("nothing special here") == []
    s = Searcher(index=index)
    top = s.search("giant", idf="classic", k=2)
    assert top[0][1]["id"] == "d1" and "size_xlarge" in top[0][2]


def test_compare_returns_every_method(index):
    s = Searcher(index=index)
    term_table, results = s.compare("small pug", k=2)
    assert set(results) == {"classic", "smooth", "max", "none"}
    assert [t for t, _, _ in term_table] == ["small", "pug", "size_small", "size_xsmall"]
    assert results["classic"][0][1]["id"] == "d0"
