"""Lower-case [a-z0-9_]+ tokens ("dog's" -> "dogs"), no lemmatisation (course rule); "_" keeps facet tokens whole."""
import re

TOKEN_RE = re.compile(r"[a-z0-9_]+")
APOSTROPHE_RE = re.compile(r"[’'`]")
MIN_LEN = 2


def tokenize(text):
    text = APOSTROPHE_RE.sub("", text.lower())
    return [t for t in TOKEN_RE.findall(text) if len(t) >= MIN_LEN]
