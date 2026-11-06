"""Extracted JSONL records -> index documents with facet tokens (shedding_2, shedding_low, size_small, ...)."""
import json
import re

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
    return {"id": f"breed:{rec['slug']}", "type": "breed", "title": rec["name"], "url": rec["url"],
            "text": with_title_boost(rec["name"], "\n".join(p for p in parts if p)), "facets": breed_facets(rec)}


def article_document(rec):
    facets = [f"category_{slugify(rec['category'])}"] + [f"tag_{slugify(t)}" for t in rec.get("tags", [])]
    text = with_title_boost(rec["title"], "\n".join(p for p in (rec["description"], rec["text"]) if p))
    return {"id": f"article:{rec['slug']}", "type": "article", "title": rec["title"], "url": rec["url"],
            "text": text, "facets": facets}


def list_document(rec):
    text = with_title_boost(rec["title"], "\n".join(p for p in (rec["description"], rec["text"]) if p))
    return {"id": f"list:{rec['slug']}", "type": "list", "title": rec["title"], "url": rec["url"],
            "text": text, "facets": [f"lists_{s.replace('-', '_')}" for s in rec["breeds"]]}


def load_documents(extracted_dir):
    docs = []
    for name, builder in (("breeds", breed_document), ("articles", article_document), ("pages", list_document)):
        path = extracted_dir / f"{name}.jsonl"
        if path.exists():
            for line in path.read_text(encoding="utf-8").split("\n"):
                if line.strip():
                    docs.append(builder(json.loads(line)))
    return docs
