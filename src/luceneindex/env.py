"""PyLucene start-up and the analyzers of the index."""
import lucene

from luceneindex.schema import TEXT_FIELDS

_vm = None
NAME_GAP = 100   # position gap between two values of a multi-valued field, so no phrase spans two names


def init():
    global _vm
    if _vm is None:
        _vm = lucene.initVM(vmargs=["-Djava.awt.headless=true"])
    else:
        _vm.attachCurrentThread()
    return _vm


def build_analyzers():
    """{"names", "english", "keyword", "fields"}; "fields" is the per-field wrapper used by the writer and the parser."""
    from java.util import HashMap
    from org.apache.lucene.analysis.custom import CustomAnalyzer
    from org.apache.lucene.analysis.miscellaneous import PerFieldAnalyzerWrapper

    def custom(tokenizer, filters):
        b = CustomAnalyzer.builder().withTokenizer(tokenizer, []).withPositionIncrementGap(NAME_GAP)
        for f in filters:
            b = b.addTokenFilter(f, [])
        return b.build()

    # names: no stemming and no stop words, so fuzzy and phrase queries see the real words ("Slovenský" -> slovensky)
    names = custom("standard", ["englishPossessive", "lowercase", "asciiFolding"])
    # prose: English stop words and Porter stemming (shedding, sheds -> shed)
    english = custom("standard", ["englishPossessive", "lowercase", "asciiFolding", "stop", "porterStem"])
    keyword = custom("keyword", ["lowercase"])
    by_name = {"names": names, "english": english}
    per_field = HashMap()
    for field, (analyzer, _) in TEXT_FIELDS.items():
        per_field.put(field, by_name[analyzer])
    return {"names": names, "english": english, "keyword": keyword,
            "fields": PerFieldAnalyzerWrapper(keyword, per_field)}


def analyze(analyzer, text, field="f"):
    from org.apache.lucene.analysis.tokenattributes import CharTermAttribute

    stream = analyzer.tokenStream(field, text)
    term = stream.addAttribute(CharTermAttribute.class_)
    stream.reset()
    out = []
    while stream.incrementToken():
        out.append(term.toString())
    stream.end()
    stream.close()
    return out
