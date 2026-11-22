"""Joined Spark records -> flat field dicts for the Lucene index (no Lucene import, testable without Java)."""
import re
from pathlib import Path

from indexer.documents import TRAIT_FACETS, read_jsonl, slugify

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def new_doc(doc_id, doc_type, title, url):
    return {"id": doc_id, "type": doc_type, "title": title, "url": url,
            "text": {}, "keyword": {}, "int": {}, "double": {}}


def _join(*parts):
    return "\n".join(p for p in parts if p)


def _unique(*lists):
    seen, out = set(), []
    for value in (v for lst in lists for v in (lst or [])):
        if value and value.lower() not in seen:
            seen.add(value.lower())
            out.append(value)
    return out


def _keywords(doc, field, values):
    out = doc["keyword"].setdefault(field, [])
    for v in values:
        if v and v not in out:
            out.append(v)
    if not out:
        del doc["keyword"][field]


def _range(lo, hi):
    if lo is None and hi is None:
        return None
    return (lo if lo is not None else hi, hi if hi is not None else lo)


def ranges_agree(a, b, tol=0.1):
    return a[0] <= b[1] * (1 + tol) and b[0] <= a[1] * (1 + tol)


def pick_range(akc, wiki):
    """AKC range unless the wiki range disagrees with it (AKC's Beagle weight fields hold the height in inches)."""
    if akc and wiki and not ranges_agree(akc, wiki):
        return wiki
    return akc or wiki


def _set_range(doc, name, unit, rng):
    if rng:
        doc["double"][f"{name}_min_{unit}"], doc["double"][f"{name}_max_{unit}"] = float(rng[0]), float(rng[1])


def _ints(doc, pairs):
    for field, value in pairs:
        if value is not None:
            doc["int"][field] = int(value)


def _wiki_common(doc, w):
    """Fields a wiki breed article gives, for AKC breeds joined to it and for wiki-only breeds."""
    disease_titles = [d["title"] for d in w.get("diseases") or []]
    _keywords(doc, "origin", [slugify(c) for c in (w.get("origin_countries") or []) + (w.get("country") or [])])
    _keywords(doc, "registry", [slugify(r) for r in w.get("registries") or []] + (["fci"] if w.get("fci_number") else []))
    _keywords(doc, "disease", [slugify(t) for t in disease_titles])
    _ints(doc, (("fci_group", w.get("fci_group")), ("fci_number", w.get("fci_number"))))
    if w.get("life_expectancy_study"):
        doc["double"]["life_study"] = float(w["life_expectancy_study"])
    return disease_titles


def breed_fields(rec):
    w = rec.get("wiki") or {}
    doc = new_doc(f"breed:{rec['slug']}", "breed", rec["name"], rec["url"])
    disease_titles = _wiki_common(doc, w)
    doc["text"] = {
        "title": rec["name"],
        "names": _unique([rec["name"]], rec["nicknames"], [w.get("title")], w.get("names"), w.get("altnames"),
                         w.get("nicknames")),
        "summary": _join(rec["text_blurb"], w.get("lead")),
        "temperament": _join(", ".join(rec["temperament"]), w.get("temperament")),
        "health": _join(rec["text_health"], ", ".join(rec["health_tests"]), w.get("health"), ", ".join(disease_titles)),
        "care": _join(rec["text_grooming"], rec["text_exercise"], rec["text_training"], rec["text_nutrition"]),
        "history": _join(rec["text_history"], w.get("history")),
        "body": _join(" ".join(p for p in (rec["group"], rec["origin"], rec["size"]) if p), rec["text_about"],
                      " ".join(rec["did_you_know"])),
        "appearance": _join(" ".join(s["text"] for s in rec.get("standard") or []), rec["height_display"],
                            rec["weight_display"], ", ".join(rec["colors"]), w.get("appearance"), w.get("coat"),
                            w.get("colour")),
    }
    _keywords(doc, "slug", [rec["slug"]])
    _keywords(doc, "group", [slugify(rec["group"].replace(" Group", ""))] if rec.get("group") else [])
    _keywords(doc, "size", [slugify(rec["size"])] if rec.get("size") else [])
    origins = doc["keyword"].pop("origin", [])
    _keywords(doc, "origin", [slugify(rec["origin"])] + origins if rec.get("origin") else origins)
    _keywords(doc, "coat_type", [slugify(v) for v in rec["traits"].get("coat_type") or []])
    _keywords(doc, "coat_length", [slugify(v) for v in rec["traits"].get("coat_length") or []])
    _keywords(doc, "registry", ["akc"])
    _keywords(doc, "wiki_url", [w.get("url")])
    for key, name in TRAIT_FACETS.items():
        score = rec["traits"].get(key)
        if isinstance(score, int) and score > 0:
            doc["int"][name] = score
    _ints(doc, (("life_min", rec.get("life_min")), ("life_max", rec.get("life_max")),
                ("popularity", rec.get("popularity_rank")), ("year", rec.get("year_recognized"))))
    _set_range(doc, "height", "cm", pick_range(_range(rec["height_min_cm"], rec["height_max_cm"]),
                                               _range(w.get("height_min_cm"), w.get("height_max_cm"))))
    _set_range(doc, "weight", "kg", pick_range(_range(rec["weight_min_kg"], rec["weight_max_kg"]),
                                               _range(w.get("weight_min_kg"), w.get("weight_max_kg"))))
    return doc


def wiki_breed_fields(w):
    doc = new_doc(f"wiki-breed:{w['page_id']}", "wiki-breed", w["title"], w["url"])
    disease_titles = _wiki_common(doc, w)
    doc["text"] = {
        "title": w["title"],
        "names": _unique([w["title"]], w.get("names"), w.get("altnames"), w.get("nicknames")),
        "summary": w.get("lead", ""),
        "temperament": w.get("temperament", ""),
        "health": _join(w.get("health"), ", ".join(disease_titles)),
        "history": w.get("history", ""),
        "body": " ".join(w.get("country") or []),
        "appearance": _join(w.get("appearance"), w.get("coat"), w.get("colour")),
    }
    _keywords(doc, "extinct", ["true"] if w.get("extinct") else [])
    _set_range(doc, "height", "cm", _range(w.get("height_min_cm"), w.get("height_max_cm")))
    _set_range(doc, "weight", "kg", _range(w.get("weight_min_kg"), w.get("weight_max_kg")))
    return doc


def disease_fields(d):
    doc = new_doc(f"disease:{d['page_id']}", "disease", d["title"], d["url"])
    doc["text"] = {
        "title": d["title"],
        "names": _unique([d["title"]], d.get("synonyms")),
        "summary": d.get("lead", ""),
        "breeds": _unique(sorted(set((d.get("akc_breeds") or []) + (d.get("wiki_breeds") or [])))),
        "body": d.get("specialty", ""),
    }
    _keywords(doc, "disease", [slugify(d["title"])])
    return doc


def article_fields(rec):
    doc = new_doc(f"article:{rec['slug']}", "article", rec["title"], rec["url"])
    doc["text"] = {"title": rec["title"], "summary": rec["description"], "body": rec["text"]}
    _keywords(doc, "category", [slugify(rec["category"])])
    _keywords(doc, "tag", [slugify(t) for t in rec.get("tags") or []])
    _keywords(doc, "author", [slugify(rec["author"])] if rec.get("author") else [])
    m = _DATE_RE.match(rec.get("published") or "")
    if m:
        doc["int"]["published"] = int("".join(m.groups()))
    return doc


def list_fields(rec, breed_names):
    doc = new_doc(f"list:{rec['slug']}", "list", rec["title"], rec["url"])
    doc["text"] = {"title": rec["title"], "summary": rec["description"], "body": rec["text"],
                   "breeds": [breed_names[s] for s in rec["breeds"] if s in breed_names]}
    _keywords(doc, "breed", rec["breeds"])
    return doc


def load_field_docs(akc_dir, joined_dir):
    """All index documents: AKC breeds joined with Wikipedia, wiki-only breeds, diseases, AKC articles and lists."""
    akc_dir, joined_dir = Path(akc_dir), Path(joined_dir)
    breeds = [breed_fields(r) for r in read_jsonl(joined_dir / "breeds")]
    names = {d["keyword"]["slug"][0]: d["title"] for d in breeds}
    return (breeds
            + [wiki_breed_fields(r) for r in read_jsonl(joined_dir / "wiki_only_breeds")]
            + [disease_fields(r) for r in read_jsonl(joined_dir / "diseases")]
            + [article_fields(r) for r in read_jsonl(akc_dir / "articles")]
            + [list_fields(r, names) for r in read_jsonl(akc_dir / "pages")])
