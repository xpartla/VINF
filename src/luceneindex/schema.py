"""Fields of the Lucene index (pure Python, shared by the document builder, the query planner and the Lucene layer)."""
from indexer.documents import TRAIT_FACETS

# analysed fields: name -> (analyzer, boost in the free-text query)
TEXT_FIELDS = {
    "names": ("names", 4.0),
    "title": ("english", 3.0),
    "summary": ("english", 2.0),
    "temperament": ("english", 1.5),
    "health": ("english", 1.5),
    "breeds": ("names", 1.0),
    "care": ("english", 1.0),
    "body": ("english", 1.0),
    "history": ("english", 0.5),
    "appearance": ("english", 0.5),
}
STORED_TEXT = ("title", "summary")
OMIT_NORMS = ("names",)   # a list of names: more alternative names must not lower the BM25 score
PHRASE_FIELDS = ("names", "title", "summary", "temperament", "health", "body")
FUZZY_FIELDS = ("names",)

KEYWORD_FIELDS = ("id", "type", "slug", "group", "size", "origin", "coat_type", "coat_length", "registry", "disease",
                  "extinct", "category", "tag", "author", "breed", "wiki_url")
TRAITS = tuple(TRAIT_FACETS.values())
INT_FIELDS = TRAITS + ("fci_group", "fci_number", "life_min", "life_max", "popularity", "year", "published")
DOUBLE_FIELDS = ("height_min_cm", "height_max_cm", "weight_min_kg", "weight_max_kg", "life_study")
SORT_FIELDS = {"popularity": False, "published": True}   # field -> descending

DOC_TYPES = ("breed", "wiki-breed", "disease", "article", "list")
