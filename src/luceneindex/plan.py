"""Natural query -> query plan: free text, quoted phrases, -exclusions and field constraints (terms and ranges).

The phrase rules of the part-1 query expansion are reused, their facet tokens become field constraints; numeric
rules (kg, lb, cm, inches, years) are new, the old index had no numeric fields."""
import math
import re

from indexer.query_expand import expand_query
from luceneindex.schema import TRAITS

LEVELS = {"low": (1, 2), "medium": (3, 3), "high": (4, 5)}
LONG_LIFE, SHORT_LIFE = 14, 10          # the thresholds of the part-1 lifespan facets

_QUOTED_RE = re.compile(r'"([^"]+)"')
_EXCLUDE_RE = re.compile(r"(?:^|\s)-(\w[\w'-]*)")
_EXTINCT_RE = re.compile(r"\bextinct\b", re.IGNORECASE)
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"\s*(kg|kilos?|kilograms?|lbs?|pounds?|cm|centimet(?:er|re)s?|inch(?:es)?)\b"
_UNDER = r"under|below|less than|lighter than|smaller than|shorter than|up to|at most|max(?:imum)?|no more than"
_OVER = r"over|above|more than|heavier than|bigger than|taller than|at least|min(?:imum)?|longer than"
_BETWEEN_RE = re.compile(rf"\b(?:between\s+)?{_NUM}\s*(?:-|–|to|and)\s*{_NUM}{_UNIT}", re.IGNORECASE)
_BOUND_RE = re.compile(rf"\b(?:({_UNDER})|({_OVER}))\s*{_NUM}{_UNIT}", re.IGNORECASE)
_LIFE_RE = re.compile(rf"\b(?:lives?|living|life\s*span|life expectancy|lifespan)\s+(?:of\s+|is\s+)?"
                      rf"(?:({_UNDER})|({_OVER}))?\s*{_NUM}\s*\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)
UNIT_FACTORS = {"kg": ("weight", "kg", 1.0), "kilo": ("weight", "kg", 1.0), "kilogram": ("weight", "kg", 1.0),
                "lb": ("weight", "kg", 0.45359237), "pound": ("weight", "kg", 0.45359237),
                "cm": ("height", "cm", 1.0), "centimeter": ("height", "cm", 1.0), "centimetre": ("height", "cm", 1.0),
                "inch": ("height", "cm", 2.54)}


def _unit(raw):
    raw = raw.lower().rstrip("s")
    return UNIT_FACTORS.get("inch" if raw.startswith("inch") else raw)


def constraint(label, clauses, op="or"):
    return {"label": label, "op": op, "clauses": clauses}


def facet_clause(token):
    """Facet token of the part-1 query expansion -> (group key, clause)."""
    m = re.fullmatch(r"fci_group_(\d+)", token)
    if m:
        return "fci_group", ("range", "fci_group", int(m.group(1)), int(m.group(1)))
    m = re.fullmatch(r"([a-z]+)_(low|medium|high)", token)
    if m and m.group(1) in TRAITS:
        return m.group(1), ("range", m.group(1)) + LEVELS[m.group(2)]
    if token == "lifespan_long":
        return "life", ("range", "life_max", LONG_LIFE, None)
    if token == "lifespan_short":
        return "life", ("range", "life_max", None, SHORT_LIFE)
    for prefix in ("size", "group", "origin", "disease"):
        if token.startswith(prefix + "_") and not token[len(prefix) + 1:].isdigit():   # "from 2024" is no origin
            return prefix, ("term", prefix, token[len(prefix) + 1:])
    return None, None


def clause_label(clause):
    if clause[0] == "term":
        return f"{clause[1]}:{clause[2]}"
    _, field, lo, hi = clause
    if lo == hi:
        return f"{field}={lo}"
    return f"{field} {'' if lo is None else lo}..{'' if hi is None else hi}"


def facet_constraints(tokens):
    """Tokens on the same field are alternatives (size small OR xsmall); different fields are separate constraints."""
    groups = {}
    for tok in tokens:
        key, clause = facet_clause(tok)
        if clause and clause not in groups.setdefault(key, []):
            groups[key].append(clause)
    out = []
    for key, clauses in groups.items():
        if key == "life":   # the measured life expectancy of the wiki counts as well
            clauses = clauses + [("range", "life_study", None if c[2] is None else float(c[2]),
                                  None if c[3] is None else float(c[3])) for c in clauses]
        out.append(constraint(" | ".join(clause_label(c) for c in clauses), clauses))
    return out


def numeric_constraints(query):
    """(constraints, query with the matched spans removed)."""
    out = []

    def between(m):
        unit = _unit(m.group(3))
        lo, hi = sorted((float(m.group(1)) * unit[2], float(m.group(2)) * unit[2]))
        name, u = unit[0], unit[1]
        out.append(constraint(f"{name} {lo:g}-{hi:g} {u}", [("range", f"{name}_min_{u}", None, round(hi, 1)),
                                                             ("range", f"{name}_max_{u}", round(lo, 1), None)], "and"))
        return " "

    def bound(m):
        name, u, factor = _unit(m.group(4))
        value = round(float(m.group(3)) * factor, 1)
        if m.group(1):
            out.append(constraint(f"{name} <= {value:g} {u}", [("range", f"{name}_max_{u}", None, value)]))
        else:
            out.append(constraint(f"{name} >= {value:g} {u}", [("range", f"{name}_min_{u}", value, None)]))
        return " "

    def life(m):
        years = float(m.group(3))
        if m.group(1):
            out.append(constraint(f"life <= {years:g} y", [("range", "life_max", None, math.floor(years)),
                                                          ("range", "life_study", None, years)]))
        else:
            out.append(constraint(f"life >= {years:g} y", [("range", "life_max", math.ceil(years), None),
                                                          ("range", "life_study", years, None)]))
        return " "

    rest = _BETWEEN_RE.sub(between, query)
    rest = _BOUND_RE.sub(bound, rest)
    rest = _LIFE_RE.sub(life, rest)
    return out, rest


def parse(query):
    phrases = [p.strip() for p in _QUOTED_RE.findall(query) if p.strip()]
    rest = _QUOTED_RE.sub(" ", query)
    exclude = [w.lower() for w in _EXCLUDE_RE.findall(rest)]
    rest = _EXCLUDE_RE.sub(" ", rest)
    facets = facet_constraints(expand_query(rest))
    numeric, rest = numeric_constraints(rest)
    return {"text": " ".join(rest.split()), "phrases": phrases, "exclude": exclude, "constraints": facets + numeric,
            "extinct": bool(_EXTINCT_RE.search(query))}


def satisfies(c, fields):
    """Does a hit (its stored fields) meet a constraint? Used to show which constraints a result fulfils."""
    def one(clause):
        if clause[0] == "term":
            return clause[2] in fields.get(clause[1], [])
        _, field, lo, hi = clause
        v = fields.get(field)
        return v is not None and (lo is None or v >= lo) and (hi is None or v <= hi)

    results = [one(cl) for cl in c["clauses"]]
    return all(results) if c["op"] == "and" else any(results)
