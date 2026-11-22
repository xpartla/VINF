"""One <page> wikitext -> ("breed" | "disease" | "other", record)."""
import html
import re
from urllib.parse import quote

from .infobox import breed_attributes, condition_attributes
from .wikitext import (categories, finish_text, protect_links, protected_link_targets, reduce_templates, sections,
                       strip_markup_noise)

BREED_INFOBOX_NAME_RE = re.compile(r"^infobox[ _]*dog[ _]*breed\b")
CONDITION_INFOBOX_NAME_RE = re.compile(r"^infobox[ _]*(?:medical[ _]*condition|disease)")
DISEASE_CATEGORY_RE = re.compile(
    r"^(?:dog diseases|.*\b(?:diseases?|disorders?|cancers?|syndromes?|infections?)\b.*\b(?:dogs?|canines?)\b|"
    r"(?:dogs?|canine)\b.*\b(?:diseases?|disorders?|cancers?|syndromes?|infections?))$", re.I)
ORIGIN_CATEGORY_RE = re.compile(r"^(?:dog|animal) breeds originating (?:in|from) (?:the )?(.+)$", re.I)
NOT_ARTICLE_TITLE_RE = re.compile(r"^(?:list|lists|outline|index|glossary) of\b", re.I)
SECTION_KINDS = {
    "temperament": re.compile(r"\b(?:temperament|behaviou?r|personality|character|disposition)\b", re.I),
    "health": re.compile(r"\b(?:health|diseases?|disorders?|longevity|life ?span|life expectancy)\b", re.I),
    "history": re.compile(r"\b(?:history|origins?|etymology)\b", re.I),
    "appearance": re.compile(r"\b(?:appearance|description|characteristics|coat|size)\b", re.I),
}
# "a median life expectancy (95% CI) of 13.2 (13.1–13.2) years", "a life expectancy of 12.5 years"
LIFE_STUDY_RE = re.compile(r"\blife (?:expectancy|span)\b[^.]{0,40}?\bof (\d+(?:\.\d+)?)(?: \([^)]*\))? years", re.I)
WIKI_URL = "https://en.wikipedia.org/wiki/"


def page_url(title):
    return WIKI_URL + quote(title.replace(" ", "_"), safe="()_,'!:-.")


def classify(title, infobox_names, cats):
    """Breed = {{Infobox dog breed}} (the breed categories also hold kennel clubs, dog types and lists)."""
    if NOT_ARTICLE_TITLE_RE.match(title):
        return "other"
    if any(BREED_INFOBOX_NAME_RE.match(n) for n in infobox_names):
        return "breed"
    if any(DISEASE_CATEGORY_RE.match(c) for c in cats):
        return "disease"
    return "other"


def section_texts(reduced):
    """{kind: {headings, text, links}}; a sub-section whose heading names no kind inherits its parent's kind."""
    out, stack = {}, []   # stack of (level, kind)
    for level, heading, body in sections(reduced)[1:]:
        while stack and stack[-1][0] >= level:
            stack.pop()
        kind = next((k for k, rx in SECTION_KINDS.items() if rx.search(heading)), None)
        if kind is None and stack:
            kind = stack[-1][1]
        stack.append((level, kind))
        if kind is None:
            continue
        sec = out.setdefault(kind, {"headings": [], "text": [], "links": []})
        sec["headings"].append(heading)
        sec["text"].append(finish_text(body))
        sec["links"] += [t for t in protected_link_targets(body) if t not in sec["links"]]
    for sec in out.values():
        sec["text"] = "\n".join(t for t in sec["text"] if t)
    return out


def parse_page(page_id, title, xml_text):
    text = html.unescape(xml_text or "")
    cats = categories(text)
    reduced, kept = reduce_templates(protect_links(strip_markup_noise(text)), keep=lambda n: n.startswith("infobox"))
    infobox_names = [b.split("|")[0].strip().lower().replace("_", " ") for b in kept]
    kind = classify(title, infobox_names, cats)
    if kind == "other":
        return "other", None

    lead_raw = sections(reduced)[0][2]
    rec = {"page_id": page_id, "title": title, "url": page_url(title), "categories": cats,
           "lead": finish_text(lead_raw)}
    if kind == "breed":
        body = next((b for b, n in zip(kept, infobox_names) if BREED_INFOBOX_NAME_RE.match(n)), None)
        rec["has_infobox"] = body is not None
        rec.update(breed_attributes(body) if body is not None else {})
        rec["origin_countries"] = [m.group(1) for m in map(ORIGIN_CATEGORY_RE.match, cats) if m]
        rec["extinct"] = any(c.lower() == "extinct dog breeds" for c in cats)
        secs = section_texts(reduced)
        for name in SECTION_KINDS:
            rec[name] = secs.get(name, {}).get("text", "")
        rec["health_links"] = secs.get("health", {}).get("links", [])
        study = LIFE_STUDY_RE.search(rec["health"])
        rec["life_expectancy_study"] = float(study.group(1)) if study else None
        rec["section_headings"] = {k: v["headings"] for k, v in secs.items()}
    else:
        body = next((b for b, n in zip(kept, infobox_names) if CONDITION_INFOBOX_NAME_RE.match(n)), None)
        rec.update(condition_attributes(body) if body is not None else {"synonyms": [], "specialty": ""})
        rec["dog_categories"] = [c for c in cats if DISEASE_CATEGORY_RE.match(c)]
    return kind, rec
