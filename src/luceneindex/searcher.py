"""Lucene searcher: query plan -> BooleanQuery of term, range, phrase and fuzzy clauses; Lucene query syntax; explain."""
import re
from pathlib import Path

from crawler import config
from luceneindex import env
from luceneindex import plan as qplan
from luceneindex.schema import (DOUBLE_FIELDS, FUZZY_FIELDS, INT_FIELDS, KEYWORD_FIELDS, PHRASE_FIELDS, SORT_FIELDS,
                                TEXT_FIELDS)

INDEX_DIR = config.DATA_DIR / "lucene" / "index"
CONSTRAINT_BOOST = 20.0    # one fulfilled constraint = a rare word (idf ~5) in the names field (boost 4)
PROXIMITY_BOOST = 1.0     # x field boost, for two query words next to each other in a field
FUZZY_MAX_DF = 2          # a word missing from all names and this rare in the prose is taken as a misspelling
_MATCH_RE = re.compile(r'weight\((\w+):("[^"]*"(?:~\d+)?|\S+?) in \d+\)')
_FUZZY_TERM_RE = re.compile(r"\bnames:(\w+)")


def fuzzy_edits(word):
    return 1 if len(word) <= 5 else 2


class LuceneSearcher:
    def __init__(self, index_dir=INDEX_DIR, similarity="bm25", directory=None):
        env.init()
        from org.apache.lucene.index import DirectoryReader
        from org.apache.lucene.search import IndexSearcher
        from org.apache.lucene.util import QueryBuilder

        if directory is None:
            from java.nio.file import Paths
            from org.apache.lucene.store import FSDirectory
            directory = FSDirectory.open(Paths.get(str(Path(index_dir).resolve())))
        self.reader = DirectoryReader.open(directory)
        self.searcher = IndexSearcher(self.reader)
        self.set_similarity(similarity)
        self.analyzers = env.build_analyzers()
        self.builders = {name: QueryBuilder(self.analyzers[name]) for name in ("names", "english")}
        self.parser = self._syntax_parser()

    def set_similarity(self, name):
        from org.apache.lucene.search.similarities import BM25Similarity, ClassicSimilarity

        self.similarity = name
        self.searcher.setSimilarity(BM25Similarity() if name == "bm25" else ClassicSimilarity())

    # --- clauses -----------------------------------------------------------------------------------------------
    def _field_query(self, field, text, slop=None):
        builder = self.builders[TEXT_FIELDS[field][0]]
        return builder.createBooleanQuery(field, text) if slop is None else builder.createPhraseQuery(field, text, slop)

    def _should(self, queries):
        from org.apache.lucene.search import BooleanClause, BooleanQuery, BoostQuery

        b, n = BooleanQuery.Builder(), 0
        for q, boost in queries:
            if q is not None:
                b.add(BoostQuery(q, boost), BooleanClause.Occur.SHOULD)
                n += 1
        return b.build() if n else None

    def text_query(self, text):
        """Every text field, each a SHOULD of the analysed words, weighted by the field boost."""
        return self._should((self._field_query(f, text), boost) for f, (_, boost) in TEXT_FIELDS.items())

    def proximity_query(self, text):
        """Phrase (slop 1) for each pair of neighbouring query words."""
        from org.apache.lucene.search import PhraseQuery

        words = env.analyze(self.analyzers["names"], text)
        queries = []
        for a, b in zip(words, words[1:]):
            for f in PHRASE_FIELDS:
                q = self._field_query(f, f"{a} {b}", 1)
                if q is not None and PhraseQuery.instance_(q):
                    queries.append((q, PROXIMITY_BOOST * TEXT_FIELDS[f][1]))
        return self._should(queries)

    def phrase_query(self, phrase):
        """A quoted phrase: the exact phrase in any phrase field."""
        return self._should((self._field_query(f, phrase, 0), TEXT_FIELDS[f][1]) for f in PHRASE_FIELDS)

    def misspelled(self, text):
        from org.apache.lucene.index import Term

        out = []
        for word in env.analyze(self.analyzers["names"], text):
            if len(word) < 4 or not word.isalpha() or word in out:
                continue
            if any(self.reader.docFreq(Term(f, word)) for f in FUZZY_FIELDS):
                continue
            stems = env.analyze(self.analyzers["english"], word)
            if not stems:   # a stop word
                continue
            if sum(self.reader.docFreq(Term(f, stems[0])) for f in ("title", "summary", "body")) <= FUZZY_MAX_DF:
                out.append(word)
        return out

    def fuzzy_query(self, words):
        from org.apache.lucene.index import Term
        from org.apache.lucene.search import FuzzyQuery

        return self._should((FuzzyQuery(Term(f, w), fuzzy_edits(w), 1), TEXT_FIELDS[f][1])
                            for w in words for f in FUZZY_FIELDS)

    def fuzzy_expansions(self, word):
        from org.apache.lucene.index import Term
        from org.apache.lucene.search import FuzzyQuery

        found = []
        for f in FUZZY_FIELDS:
            rewritten = self.searcher.rewrite(FuzzyQuery(Term(f, word), fuzzy_edits(word), 1)).toString()
            found += [t for t in _FUZZY_TERM_RE.findall(rewritten) if t not in found]
        return found

    def clause_query(self, clause):
        from java.lang import Double, Integer
        from org.apache.lucene.document import DoubleField, IntField
        from org.apache.lucene.index import Term
        from org.apache.lucene.search import TermQuery

        if clause[0] == "term":
            return TermQuery(Term(clause[1], clause[2]))
        _, field, lo, hi = clause
        if field in DOUBLE_FIELDS:
            return DoubleField.newRangeQuery(field, Double.NEGATIVE_INFINITY if lo is None else float(lo),
                                             Double.POSITIVE_INFINITY if hi is None else float(hi))
        return IntField.newRangeQuery(field, Integer.MIN_VALUE if lo is None else int(lo),
                                      Integer.MAX_VALUE if hi is None else int(hi))

    def constraint_query(self, c):
        from org.apache.lucene.search import BooleanClause, BooleanQuery

        if len(c["clauses"]) == 1:
            return self.clause_query(c["clauses"][0])
        occur = BooleanClause.Occur.MUST if c["op"] == "and" else BooleanClause.Occur.SHOULD
        b = BooleanQuery.Builder()
        for clause in c["clauses"]:
            b.add(self.clause_query(clause), occur)
        return b.build()

    def known(self, c):
        """The constraint without term clauses on values missing from the index ("from biting"), None if empty."""
        from org.apache.lucene.index import Term

        clauses = [cl for cl in c["clauses"] if cl[0] != "term" or self.reader.docFreq(Term(cl[1], cl[2]))]
        if not clauses or (c["op"] == "and" and len(clauses) < len(c["clauses"])):
            return None
        return dict(c, clauses=clauses)

    # --- whole query -------------------------------------------------------------------------------------------
    def build_query(self, p, doc_type=None, strict=False):
        """(Lucene query, notes) for a query plan of plan.parse(); notes: misspelled words, used and ignored
        constraints."""
        from org.apache.lucene.index import Term
        from org.apache.lucene.search import BooleanClause, BooleanQuery, BoostQuery, ConstantScoreQuery, TermQuery

        Occur = BooleanClause.Occur
        b = BooleanQuery.Builder()
        misspelled = self.misspelled(p["text"]) if p["text"] else []
        for q in (self.text_query(p["text"]) if p["text"] else None,
                  self.proximity_query(p["text"]) if p["text"] else None,
                  self.fuzzy_query(misspelled) if misspelled else None):
            if q is not None:
                b.add(q, Occur.SHOULD)
        for phrase in p["phrases"]:
            q = self.phrase_query(phrase)
            if q is not None:
                b.add(q, Occur.MUST)
        used = [self.known(c) for c in p["constraints"]]
        notes = {"misspelled": misspelled, "constraints": [c for c in used if c],
                 "ignored": [c["label"] for c, u in zip(p["constraints"], used) if not u]}
        for c in notes["constraints"]:
            q = self.constraint_query(c)
            if strict:
                b.add(q, Occur.FILTER)
            else:
                b.add(BoostQuery(ConstantScoreQuery(q), CONSTRAINT_BOOST), Occur.SHOULD)
        for word in p["exclude"]:
            for f in ("names", "title"):
                for token in env.analyze(self.analyzers[TEXT_FIELDS[f][0]], word):
                    b.add(TermQuery(Term(f, token)), Occur.MUST_NOT)
        if doc_type:
            b.add(TermQuery(Term("type", doc_type)), Occur.FILTER)
        if not p["extinct"]:
            b.add(TermQuery(Term("extinct", "true")), Occur.MUST_NOT)
        return b.build(), notes

    def run(self, query, k=10, sort=None):
        """(hits, total hits, exact?) for a Lucene query; sort = a field of SORT_FIELDS or None for relevance. Lucene
        counts exactly only up to 1000 hits, beyond that the total is a lower bound."""
        from org.apache.lucene.search import TotalHits

        if sort:
            from java.lang import Integer
            from org.apache.lucene.search import Sort, SortField, SortedNumericSortField

            descending = SORT_FIELDS[sort]
            sf = SortedNumericSortField(sort, SortField.Type.INT, descending)
            sf.setMissingValue(Integer(Integer.MIN_VALUE if descending else Integer.MAX_VALUE))
            top = self.searcher.search(query, k, Sort([sf, SortField.FIELD_SCORE]), True)
        else:
            top = self.searcher.search(query, k)
        stored = self.searcher.storedFields()
        exact = top.totalHits.relation() == TotalHits.Relation.EQUAL_TO
        return [self._hit(stored.document(sd.doc), sd) for sd in top.scoreDocs], top.totalHits.value(), exact

    def _hit(self, doc, sd):
        fields = {}
        for f in KEYWORD_FIELDS[2:]:
            values = list(doc.getValues(f))
            if values:
                fields[f] = values
        for f in INT_FIELDS + DOUBLE_FIELDS:
            fld = doc.getField(f)
            if fld is not None:
                num = fld.numericValue()
                fields[f] = num.doubleValue() if f in DOUBLE_FIELDS else num.intValue()
        return {"doc": sd.doc, "score": sd.score, "id": doc.get("id"), "type": doc.get("type"), "title": doc.get("title"),
                "url": doc.get("url"), "summary": doc.get("summary") or "", "fields": fields}

    def search(self, query, k=10, doc_type=None, strict=False, sort=None):
        """Natural query -> {"plan", "query", "misspelled", "constraints", "ignored", "hits", "total"}."""
        p = qplan.parse(query)
        q, notes = self.build_query(p, doc_type, strict)
        hits, total, exact = self.run(q, k, sort)
        return dict(notes, plan=p, query=q, hits=hits, total=total, exact=exact)

    # --- Lucene query syntax -----------------------------------------------------------------------------------
    def _syntax_parser(self):
        import lucene
        from java.lang import CharSequence, Double, Float, Integer
        from java.text import NumberFormat
        from java.util import HashMap, Locale
        from org.apache.lucene.queryparser.flexible.standard import StandardQueryParser
        from org.apache.lucene.queryparser.flexible.standard.config import PointsConfig, StandardQueryConfigHandler

        parser = StandardQueryParser(self.analyzers["fields"])
        points = HashMap()
        for f in INT_FIELDS:
            points.put(f, PointsConfig(NumberFormat.getIntegerInstance(Locale.ROOT), Integer.class_))
        for f in DOUBLE_FIELDS:
            points.put(f, PointsConfig(NumberFormat.getNumberInstance(Locale.ROOT), Double.class_))
        parser.setPointsConfigMap(points)
        fields = lucene.JArray("object")(len(TEXT_FIELDS), CharSequence)   # setMultiFields() rejects Python lists
        for i, f in enumerate(TEXT_FIELDS):
            fields[i] = f
        parser.getQueryConfigHandler().set(StandardQueryConfigHandler.ConfigurationKeys.MULTI_FIELDS, fields)
        boosts = HashMap()
        for f, (_, boost) in TEXT_FIELDS.items():
            boosts.put(f, Float(boost))
        parser.setFieldsBoost(boosts)
        return parser

    def syntax_search(self, text, k=10, doc_type=None, sort=None):
        """Lucene query syntax: fields, AND/OR/NOT, +/-, "phrase"~n, word~ (fuzzy), [a TO b] ranges, wildcards."""
        from org.apache.lucene.index import Term
        from org.apache.lucene.search import BooleanClause, BooleanQuery, TermQuery

        q = self.parser.parse(text, None)   # no default field: unqualified words go to every text field
        if doc_type:
            b = BooleanQuery.Builder()
            b.add(q, BooleanClause.Occur.MUST)
            b.add(TermQuery(Term("type", doc_type)), BooleanClause.Occur.FILTER)
            q = b.build()
        hits, total, exact = self.run(q, k, sort)
        return {"plan": None, "query": q, "misspelled": [], "constraints": [], "ignored": [], "hits": hits,
                "total": total, "exact": exact}

    def count(self, query):
        return self.searcher.count(query)

    # --- explanation -------------------------------------------------------------------------------------------
    def explain(self, query, docno):
        return self.searcher.explain(query, docno)

    def matched_terms(self, query, docno):
        """field:term pairs that scored for one hit, read off the Lucene explanation."""
        found = []
        for field, term in _MATCH_RE.findall(self.explain(query, docno).toString()):
            pair = f"{field}:{term}"
            if pair not in found:
                found.append(pair)
        return found
