"""Regex rules mapping query phrases to facet tokens ("does not shed" -> shedding_low)."""
import re

RULES = [
    (r"\b(?:low|little|minimal|light|no|non|doesn'?t|does not|hardly|rarely|never)[- ]*(?:shed|shedding|sheds)\b|\bhypoallergenic\b", ["shedding_low"]),
    (r"\b(?:heavy|high|lots? of|a lot of|much)[- ]*(?:shed|shedding|sheds)\b", ["shedding_high"]),
    (r"\b(?:easy|simple|quick)[- ]*(?:to[- ]*)?train(?:ed|able|ing)?\b|\b(?:highly |very )?trainable\b|\bobedient\b|\bsmart\b|\bintelligent\b", ["trainability_high"]),
    (r"\b(?:hard|difficult|stubborn)[- ]*(?:to[- ]*)?train\b|\bstubborn\b|\bindependent\b", ["trainability_low"]),
    (r"\b(?:good|great|gentle|patient|friendly|safe)[- ]*(?:with|for|around)[- ]*(?:young |small |little )?(?:kids|children|toddlers|family|families)\b|\bfamily dog\b|\bkid[- ]friendly\b", ["children_high", "affectionate_high"]),
    (r"\b(?:good|great|friendly|gets? along)[- ]*(?:with|around)[- ]*(?:other )?dogs\b", ["otherdogs_high"]),
    (r"\b(?:calm|lazy|relaxed|laid[- ]back|low[- ]energy|couch potato|mellow|quiet)\b", ["energy_low"]),
    (r"\b(?:high[- ]energy|energetic|active|athletic|lots? of exercise|running|hiking|jogging|sporty)\b", ["energy_high"]),
    (r"\b(?:quiet|rarely barks?|doesn'?t bark|does not bark|low[- ]bark(?:ing)?|not (?:a )?barker)\b", ["barking_low"]),
    (r"\b(?:apartment|flat|condo|city|small (?:home|house|space))\b", ["adaptability_high", "barking_low", "size_small", "size_medium"]),
    (r"\b(?:guard|guarding|protective|watchdog|watch dog|protection)\b", ["watchdog_high"]),
    (r"\b(?:drools?|drooling|slobber)\b", ["drooling_low"]),
    (r"\b(?:low|easy|little|minimal)[- ]*(?:grooming|maintenance|upkeep)\b|\bwash and wear\b", ["grooming_low"]),
    (r"\b(?:tiny|toy|teacup|very small|extra small|xsmall|lap ?dog)\b", ["size_xsmall", "size_small"]),
    (r"\bsmall\b", ["size_small", "size_xsmall"]),
    (r"\bmedium(?:[- ]sized?)?\b", ["size_medium"]),
    (r"\b(?:large|big)\b", ["size_large", "size_xlarge"]),
    (r"\b(?:giant|huge|extra large|xlarge|massive)\b", ["size_xlarge"]),
    (r"\b(?:long[- ]lived|long life|lives? long|longevity|long lifespan)\b", ["lifespan_long"]),
    (r"\b(?:friendly|outgoing|sociable|social)\b", ["strangers_high"]),
    (r"\b(?:playful|fun[- ]loving|goofy)\b", ["playfulness_high"]),
    (r"\b(?:herding|hound|sporting|working|terrier|toy|non[- ]sporting)\s+(?:group|breeds?|dogs?)\b", None),  # handled below
]
# "from slovakia", "originating in the czech republic", "slovak breeds" -> origin_slovakia
_ORIGIN_RE = re.compile(r"\b(?:from|originat\w*\s+(?:in|from)|bred in|native to|developed in)\s+(?:the\s+)?"
                        r"([a-z]+(?:\s+(?:republic|kingdom|states))?)\b", re.IGNORECASE)
DEMONYMS = {"slovak": "slovakia", "slovakian": "slovakia", "czech": "czech_republic", "czechoslovakian": "czechoslovakia",
            "hungarian": "hungary", "polish": "poland", "german": "germany", "austrian": "austria", "swiss": "switzerland",
            "french": "france", "belgian": "belgium", "dutch": "netherlands", "italian": "italy", "spanish": "spain",
            "portuguese": "portugal", "croatian": "croatia", "serbian": "serbia", "russian": "russia", "english": "england",
            "scottish": "scotland", "irish": "ireland", "welsh": "wales", "british": "united_kingdom",
            "japanese": "japan", "chinese": "china", "tibetan": "tibet", "korean": "korea", "mexican": "mexico",
            "american": "united_states", "canadian": "canada", "australian": "australia", "turkish": "turkey",
            "finnish": "finland", "swedish": "sweden", "norwegian": "norway", "danish": "denmark", "icelandic": "iceland"}
_DEMONYM_RE = re.compile(r"\b(%s)\s+(?:dog\s+)?(?:breeds?|dogs?)\b" % "|".join(DEMONYMS), re.IGNORECASE)
_FCI_GROUP_RE = re.compile(r"\bfci\s+group\s+(\d{1,2})\b", re.IGNORECASE)
_GROUP_RE = re.compile(r"\b(herding|hound|sporting|working|terrier|toy|non[- ]sporting)\s+(?:group|breeds?|dogs?)\b", re.IGNORECASE)
_COMPILED = [(re.compile(p, re.IGNORECASE), toks) for p, toks in RULES if toks]


def expand_query(query):
    out = []
    for rx, toks in _COMPILED:
        if rx.search(query):
            out += [t for t in toks if t not in out]
    for m in _GROUP_RE.finditer(query):
        tok = "group_" + m.group(1).lower().replace("-", "_").replace(" ", "_")
        if tok not in out:
            out.append(tok)
    origins = [m.group(1).lower() for m in _ORIGIN_RE.finditer(query)]
    origins += [DEMONYMS[m.group(1).lower()] for m in _DEMONYM_RE.finditer(query)]
    for name in origins:
        tok = "origin_" + DEMONYMS.get(name, name).replace(" ", "_")
        if tok not in out:
            out.append(tok)
    for m in _FCI_GROUP_RE.finditer(query):
        tok = f"fci_group_{int(m.group(1))}"
        if tok not in out:
            out.append(tok)
    return out
