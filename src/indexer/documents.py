"""Extracted records -> index documents with facet tokens (shedding_low, size_small, ...); with the joined Spark
output also wiki facets (origin_slovakia, fci_group_1, disease_*), wiki-only breeds and disease pages."""
import json
import re
from pathlib import Path

# AKC trait key -> short facet name
TRAIT_FACETS = {
    "shedding_level": "shedding", "energy_level": "energy", "trainability_level": "trainability",
    "barking_level": "barking", "drooling_level": "drooling", "good_with_young_children": "children",
    "good_with_other_dogs": "otherdogs", "openness_to_strangers": "strangers", "playfulness_level": "playfulness",
    "adaptability_level": "adaptability", "affectionate_with_family": "affectionate",
    "mental_stimulation_needs": "mentalstim", "watchdogprotective_nature": "watchdog",
    "coat_grooming_frequency": "grooming",
}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(s):
    return _SLUG_RE.sub("_", s.lower()).strip("_")


def level(score):
    return "low" if score <= 2 else "medium" if score == 3 else "high"


def breed_facets(rec):
    facets = []
    for key, name in TRAIT_FACETS.items():
        score = rec["traits"].get(key)
        if isinstance(score, int) and score > 0:
            facets += [f"{name}_{score}", f"{name}_{level(score)}"]
    for key in ("coat_type", "coat_length"):
        for value in rec["traits"].get(key) or []:
            facets.append(f"{key}_{slugify(value)}")
    if rec.get("size"):
        facets.append(f"size_{slugify(rec['size'])}")
    if rec.get("group"):
        facets.append(f"group_{slugify(rec['group'].replace(' Group', ''))}")
    if rec.get("origin"):
        facets.append(f"origin_{slugify(rec['origin'])}")
    if rec.get("life_max"):
        facets.append("lifespan_long" if rec["life_max"] >= 14 else "lifespan_short" if rec["life_max"] <= 10 else "lifespan_medium")
    return facets


def wiki_facets(w):
    facets = [f"origin_{slugify(c)}" for c in w.get("origin_countries") or []]
    facets += [f"origin_{slugify(c)}" for c in w.get("country") or [] if f"origin_{slugify(c)}" not in facets]
    if w.get("fci_number"):
        facets.append("fci_recognised")
    if w.get("fci_group"):
        facets.append(f"fci_group_{w['fci_group']}")
    facets += [f"disease_{slugify(d['title'])}" for d in w.get("diseases") or []]
    if w.get("extinct"):
        facets.append("extinct")
    return facets


def wiki_text(w):
    """Names, lead, temperament and health of the wiki article (history and appearance would dilute the record)."""
    names = [n for n in (w.get("names") or []) + (w.get("altnames") or []) + (w.get("nicknames") or []) if n]
    parts = [" ".join(names), w.get("lead", ""), w.get("temperament", ""), w.get("health", ""),
             " ".join(d["title"] for d in w.get("diseases") or [])]
    return "\n".join(p for p in parts if p)


TITLE_BOOST = 3   # title indexed this many times


def with_title_boost(title, text):
    return "\n".join([title] * TITLE_BOOST + [text])


def breed_document(rec):
    # standard sections (anatomy, ~1000 words) left out: they would dilute the rest
    parts = [rec["name"], " ".join(rec["nicknames"]), rec["group"], rec["origin"], rec["size"],
             " ".join(rec["temperament"]), " ".join(rec["colors"]), " ".join(rec["health_tests"]),
             rec["height_display"], rec["weight_display"],
             f"life expectancy {rec['life_min']} to {rec['life_max']} years" if rec["life_min"] else "",
             rec["text_blurb"], rec["text_about"], rec["text_health"], rec["text_grooming"], rec["text_exercise"],
             rec["text_training"], rec["text_nutrition"], rec["text_history"], " ".join(rec["did_you_know"])]
    facets = breed_facets(rec)
    if rec.get("wiki"):
        parts.append(wiki_text(rec["wiki"]))
        facets += [f for f in wiki_facets(rec["wiki"]) if f not in facets]
    return {"id": f"breed:{rec['slug']}", "type": "breed", "title": rec["name"], "url": rec["url"],
            "text": with_title_boost(rec["name"], "\n".join(p for p in parts if p)), "facets": facets}


def wiki_breed_document(w):
    """Breed known only from Wikipedia (no AKC record, so no trait facets)."""
    text = "\n".join(p for p in (wiki_text(w), " ".join(w.get("country") or []), w.get("appearance", "")) if p)
    return {"id": f"wiki-breed:{w['page_id']}", "type": "wiki-breed", "title": w["title"], "url": w["url"],
            "text": with_title_boost(w["title"], text), "facets": wiki_facets(w)}


def disease_document(d):
    breeds = sorted(set((d.get("akc_breeds") or []) + (d.get("wiki_breeds") or [])))
    text = "\n".join(p for p in (" ".join(d.get("synonyms") or []), d.get("lead", ""),
                                 "breeds: " + ", ".join(breeds) if breeds else "") if p)
    return {"id": f"disease:{d['page_id']}", "type": "disease", "title": d["title"], "url": d["url"],
            "text": with_title_boost(d["title"], text), "facets": [f"disease_{slugify(d['title'])}"]}


def article_document(rec):
    facets = [f"category_{slugify(rec['category'])}"] + [f"tag_{slugify(t)}" for t in rec.get("tags", [])]
    text = with_title_boost(rec["title"], "\n".join(p for p in (rec["description"], rec["text"]) if p))
    return {"id": f"article:{rec['slug']}", "type": "article", "title": rec["title"], "url": rec["url"],
            "text": text, "facets": facets}


def list_document(rec):
    text = with_title_boost(rec["title"], "\n".join(p for p in (rec["description"], rec["text"]) if p))
    return {"id": f"list:{rec['slug']}", "type": "list", "title": rec["title"], "url": rec["url"],
            "text": text, "facets": [f"lists_{s.replace('-', '_')}" for s in rec["breeds"]]}


def read_jsonl(path):
    """Records of a .jsonl file or of a Spark output directory (part-* files)."""
    path = Path(path)
    files = sorted(path.glob("part-*")) if path.is_dir() else [path] if path.exists() else []
    for f in files:
        for line in f.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                yield json.loads(line)


def load_documents(extracted_dir, joined_dir=None):
    """Part 1: extracted_dir/{breeds,articles,pages}.jsonl. With joined_dir (Spark output): extracted_dir is the
    Spark AKC dir, breeds come joined with Wikipedia, plus wiki-only breeds and disease pages."""
    extracted_dir = Path(extracted_dir)
    suffix = "" if joined_dir else ".jsonl"
    sources = [(joined_dir / "breeds" if joined_dir else extracted_dir / "breeds.jsonl", breed_document),
               (extracted_dir / f"articles{suffix}", article_document),
               (extracted_dir / f"pages{suffix}", list_document)]
    if joined_dir:
        sources += [(joined_dir / "wiki_only_breeds", wiki_breed_document), (joined_dir / "diseases", disease_document)]
    return [builder(rec) for path, builder in sources for rec in read_jsonl(path)]
