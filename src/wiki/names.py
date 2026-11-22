"""Breed-name join keys shared by the AKC and Wikipedia sides."""
import re
import unicodedata

WIKI_DISAMBIGUATOR_RE = re.compile(r"\s*\((?:dog|dogs|dog breed|breed|domestic dog|dog type|hound)\)\s*$", re.I)
PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")
DOG_SUFFIX_RE = re.compile(r" (?:dog|dogs)$")
VARIETY_RE = re.compile(r"\s*\(([^)]*?)\s*(?:type|variety)?\)\s*$", re.I)   # "Braque Francais (Pyrenean type)"
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
MIN_NICKNAME_KEY = 4   # "bc", "chi", "toy" would only produce accidental matches


def name_key(s):
    """Lower-case ASCII words: accents stripped, "&" -> "and", punctuation -> space."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ").replace("ß", "ss").replace("ø", "o").replace("æ", "ae").replace("ł", "l")
    return NON_ALNUM_RE.sub(" ", s).strip()


def without_dog(key):
    return DOG_SUFFIX_RE.sub("", key)


def compact(key):
    """"scent hound" / "scenthound", "wire haired" / "wirehaired" meet without spaces."""
    return key.replace(" ", "")


def akc_keys(name, nicknames=()):
    """[(key, kind)]: kind "name", then "variant" (no parenthetical, no trailing "dog"), then "nickname"."""
    out = []

    def add(key, kind):
        if key and all(k != key for k, _ in out):
            out.append((key, kind))

    base = name_key(name)
    add(base, "name")
    no_paren = name_key(PARENTHETICAL_RE.sub("", name))
    for k in (no_paren, without_dog(base), without_dog(no_paren), compact(base), compact(no_paren)):
        add(k, "variant")
    for nick in nicknames:
        k = name_key(PARENTHETICAL_RE.sub("", nick))
        if len(k) >= MIN_NICKNAME_KEY:
            add(k, "nickname")
    return out


def wiki_title_keys(title):
    """[(key, kind)] of a page or redirect title: "exact" (also without a "(dog)" disambiguator), "variant"
    (no trailing "dog", no spaces, "(Pyrenean type)" read as a variety)."""
    exact = [name_key(title), name_key(WIKI_DISAMBIGUATOR_RE.sub("", title))]
    variants = [without_dog(k) for k in exact] + [compact(k) for k in exact]
    variants.append(name_key(VARIETY_RE.sub(lambda m: " " + m.group(1), title)))
    out = []
    for kk, kind in [(k, "exact") for k in exact] + [(k, "variant") for k in variants]:
        if kk and all(kk != o for o, _ in out):
            out.append((kk, kind))
    return out


def wiki_name_keys(names):
    keys = []
    for n in names:
        k = name_key(PARENTHETICAL_RE.sub("", n))
        if len(k) >= MIN_NICKNAME_KEY and k not in keys:
            keys.append(k)
    return keys
