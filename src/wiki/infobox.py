"""Infobox body (nested templates already reduced) -> raw fields -> typed dog-breed attributes."""
import re

from .wikitext import finish_text, protected_link_targets

FIELD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_ \-]*?)\s*=(.*)$", re.S)
LIST_SPLIT_RE = re.compile(r"\s*(?:\n|;|,|/|\bor\b)\s*")
ASIDE_RE = re.compile(r"<small>.*?</small>|\(\s*see\b[^)]*\)", re.I | re.S)   # "(see [[Poodle#History|history]])"

NUM = r"(\d+(?:\.\d+)?)"
UNIT = r"(cm|mm|m|in|inch(?:es)?|″|\"|kg|kilo(?:gram)?s?|lbs?|pounds?|centimet(?:re|er)s?)"
RANGE_UNIT_RE = re.compile(NUM + r"\s*(?:[-–—]|to|and)\s*" + NUM + r"\s*" + UNIT + r"(?![a-z])", re.I)
SINGLE_UNIT_RE = re.compile(NUM + r"\s*" + UNIT + r"(?![a-z])", re.I)
COUNT_RANGE_RE = re.compile(r"(\d+)\s*(?:[-–—]|to)\s*(\d+)")
COUNT_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)")
TO_CM = {"cm": 1.0, "mm": 0.1, "m": 100.0, "in": 2.54, "″": 2.54, '"': 2.54}
TO_KG = {"kg": 1.0, "lb": 0.45359237}

# FCI standard URLs: .../Standards/043g05-en.pdf, .../uploaded_files/142gb1996_en.doc, .../SALUKI-269.html
FCI_URL_RES = (re.compile(r"/standards/(\d{1,3})g(\d{2})", re.I), re.compile(r"uploaded_files/(\d{1,3})g", re.I),
               re.compile(r"[-_/](\d{1,3})\.html?\b", re.I), re.compile(r"/(\d{1,3})g[a-z]?\d{4}", re.I))
AKC_URL_RE = re.compile(r"akc\.org/(?:dog-breeds|breeds)/([a-z0-9_-]+)", re.I)
REGISTRY_NAMES = {"fci": "FCI", "akc": "AKC", "ukc": "UKC", "ankc": "ANKC", "ckc": "CKC", "nzkc": "NZKC",
                  "kc": "KC", "kc_uk": "KC"}


def infobox_fields(body):
    """{key: raw value} of an infobox body (links still protected)."""
    fields, key = {}, None
    for part in body.split("|")[1:]:
        m = FIELD_RE.match(part)
        if m:
            key = m.group(1).strip().lower().replace(" ", "_").replace("-", "_")
            fields[key] = m.group(2).strip()
        elif key:
            fields[key] += " " + part
    return fields


def value_text(raw):
    return finish_text(raw).strip() if raw else ""


def value_list(raw):
    out = []
    for part in LIST_SPLIT_RE.split(value_text(raw)):
        part = part.strip(" .:'\"")
        if part.startswith("(") and part.endswith(")") or part.count("(") != part.count(")"):
            part = part.strip("()").strip()
        if part and part not in out:
            out.append(part)
    return out


def _unit_factor(unit):
    u = unit.lower()
    if u.startswith(("cm", "centimet")):
        return "cm", 1.0
    if u in TO_CM:
        return "cm", TO_CM[u]
    if u.startswith("inch"):
        return "cm", 2.54
    if u.startswith(("kg", "kilo")):
        return "kg", 1.0
    if u.startswith(("lb", "pound")):
        return "kg", TO_KG["lb"]
    return None, None


def measure_range(values, dimension):
    """(min, max) in cm or kg over all values (male, female, both); metric numbers preferred when both are given."""
    found = {"metric": [], "converted": []}
    for raw in values:
        text = value_text(raw).replace(",", ".")
        spans = []
        for m in RANGE_UNIT_RE.finditer(text):
            spans.append((m.span(), float(m.group(1)), float(m.group(2)), m.group(3)))
        for m in SINGLE_UNIT_RE.finditer(text):
            if not any(s <= m.start() < e for (s, e), *_ in spans):
                spans.append((m.span(), float(m.group(1)), float(m.group(1)), m.group(2)))
        for _, lo, hi, unit in spans:
            dim, factor = _unit_factor(unit)
            if dim != dimension:
                continue
            key = "metric" if factor == 1.0 or (dim == "cm" and unit.lower() in ("mm", "m")) else "converted"
            found[key] += [lo * factor, hi * factor]
    nums = found["metric"] or found["converted"]
    return (round(min(nums), 1), round(max(nums), 1)) if nums else (None, None)


def count_range(raw):
    text = value_text(raw)
    m = COUNT_RANGE_RE.search(text)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = COUNT_SINGLE_RE.search(text)
    return (float(m.group(1)), float(m.group(1))) if m else (None, None)


def fci_number(fields):
    """(number, group) from fcinum/fcigroup or from the FCI standard URL."""
    num = re.search(r"\d+", value_text(fields.get("fcinum", "")))
    grp = re.search(r"\d+", value_text(fields.get("fcigroup", "")))
    number, group = (int(num.group()) if num else None), (int(grp.group()) if grp else None)
    url = fields.get("fcistd", "")
    for rx in FCI_URL_RES:
        m = rx.search(url)
        if m:
            number = number or int(m.group(1))
            if group is None and m.lastindex and m.lastindex >= 2:
                group = int(m.group(2))
            break
    return number, group


def registries(fields):
    """Kennel clubs with a breed standard link in the infobox."""
    out = []
    for key, value in fields.items():
        if not value.strip() or not re.search(r"(?:_?std|_?standard)$", key):
            continue
        base = re.sub(r"_?(?:std|standard)$", "", key)
        name = REGISTRY_NAMES.get(base)
        if base.startswith("kc") and fields.get(base + "_name"):
            name = value_text(fields[base + "_name"]) or name
        name = name or base.upper()
        if name not in out:
            out.append(name)
    return out


def breed_attributes(body):
    f = infobox_fields(body)
    get = f.get
    names = value_list(get("name", "").replace(",", "\n"))
    height = measure_range([get(k, "") for k in ("height", "maleheight", "femaleheight", "dogheight", "bitchheight")], "cm")
    weight = measure_range([get(k, "") for k in ("weight", "maleweight", "femaleweight", "dogweight", "bitchweight")], "kg")
    litter = count_range(get("litter_size") or get("litter", ""))
    country_raw = ASIDE_RE.sub("", get("country") or get("origin", ""))
    fci_no, fci_group = fci_number(f)
    akc = AKC_URL_RE.search(" ".join(v for k, v in f.items() if "akc" in k or k.endswith("std")))
    return {
        "names": names,
        "altnames": value_list(get("altname", "")),
        "nicknames": value_list(get("nickname", "")),
        "country": protected_link_targets(country_raw) or value_list(country_raw),
        "height_min_cm": height[0], "height_max_cm": height[1],
        "weight_min_kg": weight[0], "weight_max_kg": weight[1],
        "litter_min": litter[0], "litter_max": litter[1],
        "coat": value_text(get("coat", "")),
        "colour": value_text(get("colour") or get("color", "")),
        "fci_number": fci_no, "fci_group": fci_group,
        "registries": registries(f),
        "akc_slug": akc.group(1).lower().replace("_", "-") if akc else "",
        "infobox_fields": sorted(k for k, v in f.items() if value_text(v)),
    }


def condition_attributes(body):
    """Infobox medical condition -> synonyms and field (specialty)."""
    f = infobox_fields(body)
    return {"synonyms": value_list(f.get("synonyms", "") or f.get("synonym", "")),
            "specialty": value_text(f.get("field", "") or f.get("specialty", ""))}
