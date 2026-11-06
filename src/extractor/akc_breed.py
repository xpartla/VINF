"""Regex extraction of one breed entity from the HTML-escaped JSON in data-js-props (never parsed as JSON)."""
import html
import re

from .textutil import json_text, json_unescape

PROPS_RE = re.compile(r'data-js-component="breedPage"\s+data-js-props="([^"]*)"')
SLUG_RE = re.compile(r'"current_breed":"([a-z0-9-]+)"')
# section start, e.g.  "basics":{"welsh-terrier":{
SECTIONS = ("health", "basics", "traits", "description", "standards", "colors", "clubs", "history")
SECTION_RE = re.compile(r'"(%s)":\s*\{\s*"([a-z0-9-]+)":\s*\{' % "|".join(SECTIONS))
# related breeds repeat the same keys
RELATED_ITEMS_RE = re.compile(r'"related_breeds_items(?:_url)?":')

JSON_STR = r'"((?:[^"\\]|\\.)*)"'
JSON_NUM_OR_STR = r'(?:"([^"]*)"|(-?\d+(?:\.\d+)?)|null)'   # AKC writes numbers as "15.5" or 15

LIFE_RE = re.compile(r'"life_expectancy":\s*"\s*(\d+)\s*(?:-|–|to)\s*(\d+)')
LIFE_SINGLE_RE = re.compile(r'"life_expectancy":\s*"\s*(\d+)\s*(?:\+\s*)?years?')
POPULARITY_RE = re.compile(r'"popularity_(20\d\d)":\s*(\d+)')
TRAITS = ("affectionate_with_family", "good_with_young_children", "good_with_other_dogs", "shedding_level",
          "coat_grooming_frequency", "drooling_level", "openness_to_strangers", "playfulness_level",
          "watchdogprotective_nature", "adaptability_level", "trainability_level", "energy_level",
          "barking_level", "mental_stimulation_needs")
TRAIT_SCORE_RE = re.compile(r'"(%s)":\s*\{[^{}]*?"score":\s*(\d)' % "|".join(TRAITS))
TRAIT_CHECKBOX_RE = re.compile(r'"(coat_type|coat_length)":\s*\{\s*"selected":\s*\[([^\]]*)\]')
HEALTH_TEST_RE = re.compile(r'"test_\d":\s*"((?:[^"\\]|\\.)+)"')
STANDARD_SECTION_RE = re.compile(r'"title_(\d)":\s*"((?:[^"\\]|\\.)*)",\s*"description_\1":\s*"((?:[^"\\]|\\.)*)"')
COLOR_RE = re.compile(r'"color_long":\s*"((?:[^"\\]|\\.)+)"')

# fallback: the <PageMap> comment
PAGEMAP_LIFE_RE = re.compile(r'Life Expectancy:\s*(\d+)\s*-\s*(\d+)\s*years', re.IGNORECASE)
PAGEMAP_RANK_RE = re.compile(r'AKC Breed Popularity:\s*Ranks\s*(\d+)\s*of\s*(\d+)', re.IGNORECASE)

IN_TO_CM = 2.54
LB_TO_KG = 0.45359237


def _str(section_text, key):
    m = re.search(r'"%s":\s*%s' % (key, JSON_STR), section_text)
    return json_unescape(m.group(1)) if m else ""


def _text(section_text, key):
    m = re.search(r'"%s":\s*%s' % (key, JSON_STR), section_text)
    return json_text(m.group(1)) if m else ""


def _num(section_text, key):
    m = re.search(r'"%s":\s*%s' % (key, JSON_NUM_OR_STR), section_text)
    if not m:
        return None
    raw = m.group(1) if m.group(1) is not None else m.group(2)
    try:
        return float(raw) if raw not in (None, "") else None
    except ValueError:
        return None


def _int(value):
    return int(value) if value is not None else None


def _split_list(s, sep=","):
    return [p.strip() for p in s.split(sep) if p.strip()] if s else []


def _minmax(values):
    vals = [v for v in values if v is not None]
    return (min(vals), max(vals)) if vals else (None, None)


def _round(v, factor):
    return round(v * factor, 1) if v is not None else None


def split_sections(props_text, slug):
    marks = sorted((m.start(), m.group(1)) for m in SECTION_RE.finditer(props_text) if m.group(2) == slug)
    out = {}
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(props_text)
        out[name] = props_text[pos:end]
    if "basics" in out:   # drop the nested related-breed blocks
        m = RELATED_ITEMS_RE.search(out["basics"])
        if m:
            out["basics"] = out["basics"][:m.start()]
    return out


def extract_breed(html_text, url=""):
    """Breed dict, or None if not a breed page."""
    m = PROPS_RE.search(html_text)
    if not m:
        return None
    props = html.unescape(m.group(1))
    slug_m = SLUG_RE.search(props)
    if not slug_m or "breed_data" not in props:
        return None
    slug = slug_m.group(1)
    sec = split_sections(props, slug)
    basics, traits, std = sec.get("basics", ""), sec.get("traits", ""), sec.get("standards", "")
    health, desc, hist = sec.get("health", ""), sec.get("description", ""), sec.get("history", "")

    life = LIFE_RE.search(basics) or PAGEMAP_LIFE_RE.search(html_text)
    life_min, life_max = (int(life.group(1)), int(life.group(2))) if life else (None, None)
    if life is None:
        single = LIFE_SINGLE_RE.search(basics)
        if single:
            life_min = life_max = int(single.group(1))

    h_min, h_max = _minmax([_num(std, k) for k in ("height_min_m", "height_min_f", "height_max_m", "height_max_f")])
    w_min, w_max = _minmax([_num(std, k) for k in ("weight_min_m", "weight_min_f", "weight_max_m", "weight_max_f")])

    popularity = {int(y): int(r) for y, r in POPULARITY_RE.findall(basics)}
    rank = PAGEMAP_RANK_RE.search(html_text)

    scores = {name: int(score) for name, score in TRAIT_SCORE_RE.findall(traits)}
    for name, raw_list in TRAIT_CHECKBOX_RE.findall(traits):
        scores[name] = [json_unescape(v) for v in re.findall(JSON_STR, raw_list) if not v.isdigit()]   # "0" = unset

    return {
        "url": url,
        "slug": slug,
        "name": _str(basics, "breed_name") or _str(health, "breed_name"),
        "nicknames": _split_list(_str(basics, "breed_nicknames")),
        "group": _str(basics, "breed_group"),
        "origin": _str(basics, "origin"),
        "year_recognized": _int(_num(basics, "year_recognized")) or None,   # 0 = not (yet) recognised
        "life_min": life_min,
        "life_max": life_max,
        "height_min_in": h_min, "height_max_in": h_max,
        "height_min_cm": _round(h_min, IN_TO_CM), "height_max_cm": _round(h_max, IN_TO_CM),
        "weight_min_lb": w_min, "weight_max_lb": w_max,
        "weight_min_kg": _round(w_min, LB_TO_KG), "weight_max_kg": _round(w_max, LB_TO_KG),
        "height_display": _str(std, "height_display"),
        "weight_display": _str(std, "weight_display"),
        "size": _text(std, "size"),   # sometimes wrapped in <p>...</p>
        "popularity": popularity,
        "popularity_rank": popularity.get(max(popularity)) if popularity else (int(rank.group(1)) if rank else None),
        "temperament": _split_list(_str(traits, "temperament"), "/"),
        "traits": scores,
        "health_tests": [json_unescape(t) for t in HEALTH_TEST_RE.findall(health)],
        "colors": sorted(set(json_unescape(c) for c in COLOR_RE.findall(sec.get("colors", "")))),
        "related_breeds": _split_list(_str(basics, "related_breeds")),
        "club": _str(sec.get("clubs", ""), "breed_club_name"),
        "standard_pdf": _str(std, "breed_standard_PDF"),
        "text_about": _text(desc, "akc_org_about") or _text(desc, "mp_description"),
        "text_blurb": _text(desc, "akc_org_blurb"),
        "text_health": _text(health, "akc_org_health") or _text(health, "mp_health"),
        "text_grooming": _text(health, "akc_org_grooming"),
        "text_exercise": _text(health, "akc_org_exercise"),
        "text_training": _text(health, "akc_org_training"),
        "text_nutrition": _text(health, "akc_org_nutrition"),
        "text_history": _text(hist, "akc_org_history"),
        "did_you_know": [json_text(p) for p in _str(hist, "did_you_know").split(" | ") if p.strip()],
        "standard": [{"title": json_unescape(t), "text": json_text(d)}
                     for _, t, d in STANDARD_SECTION_RE.findall(std) if t],
    }
