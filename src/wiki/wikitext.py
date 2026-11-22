"""Regex processing of wikitext: innermost-first template reduction, links, sections, categories, plain text."""
import html
import re

COMMENT_RE = re.compile(r"<!--.*?(?:-->|\Z)", re.S)
REF_RE = re.compile(r"<ref\b[^>]*/\s*>|<ref\b[^>]*>.*?</ref\s*>", re.S | re.I)
DROP_ELEMENT_RE = re.compile(r"<(gallery|timeline|math|score|syntaxhighlight|imagemap)\b[^>]*>.*?</\1\s*>", re.S | re.I)
TABLE_RE = re.compile(r"^[ \t]*\{\|.*?^[ \t]*\|\}", re.S | re.M)
INNER_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
INNER_LINK_RE = re.compile(r"\[\[([^\[\]]*)\]\]")
# a protected link: \x02target\x01label\x03 (pipes and brackets hidden from the template regex)
PROTECTED_LINK_RE = re.compile(r"\x02([^\x02\x03]*)\x03")
EXT_LINK_RE = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")
BARE_URL_RE = re.compile(r"https?://\S+")
BOLD_ITALIC_RE = re.compile(r"'{2,}")
BR_RE = re.compile(r"<br\s*/?\s*>", re.I)
TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
HEADING_RE = re.compile(r"^(={2,6})[ \t]*(.+?)[ \t]*\1[ \t]*$", re.M)
MAGIC_WORD_RE = re.compile(r"__[A-Z]+__")
LIST_MARK_RE = re.compile(r"^[*#:;]+\s*", re.M)
SPACES_RE = re.compile(r"[ \t ]+")
BLANK_LINES_RE = re.compile(r"\n\s*\n+")
CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^\]|]+?)\s*(?:\|[^\]]*)?\]\]", re.I)
LINK_TARGET_RE = re.compile(r"\[\[\s*:?\s*([^\[\]|#{}]+?)\s*(?:#[^\[\]|]*)?\s*(?:\|[^\[\]]*)?\]\]")
NON_ARTICLE_PREFIX_RE = re.compile(
    r"^(?:file|image|media|category|template|wikipedia|wp|help|portal|special|user|talk|draft|module|wikt|wiktionary|"
    r"commons|species|s|q|b|n|v|w|m|meta|[a-z]{2,3}(?:-[a-z]+)?)\s*:", re.I)
NAMED_ARG_RE = re.compile(r"^\s*([^=]+?)\s*=(.*)$", re.S)

RANGE_SEPARATORS = {"-": "–", "–": "–", "—": "–", "to": "–", "and": "–", "or": "–", "x": "×", "by": "×", "+/-": "±"}
LIST_TEMPLATES = {"ubl", "ubli", "unbulleted list", "plainlist", "plain list", "flatlist", "flat list", "hlist",
                  "bulleted list", "ublist", "collapsible list", "enum", "unordered list", "nowrap list"}
FIRST_ARG_TEMPLATES = {"nowrap", "nobr", "small", "smaller", "big", "larger", "nobold", "noitalic", "em", "strong",
                       "abbr", "sic", "flag", "flagcountry", "flagu", "flag country", "lang-en", "visible anchor",
                       "linktext", "proper name", "nihongo", "uline", "underline", "font", "resize", "vanchor",
                       "sortname", "sort", "hs", "noflag", "right", "left", "center", "centre", "align", "nowrap begin"}
LAST_ARG_TEMPLATES = {"lang", "transl", "transliteration", "native name", "langx", "lang-x", "literal translation",
                      "lit", "iast"}
CONSTANT_TEMPLATES = {"nbsp": " ", "ndash": "–", "snd": " – ", "spaced ndash": " – ", "en dash": "–", "mdash": "—",
                      "em dash": "—", "!": " ", "=": "=", "dot": "·", "middot": "·", "·": "·", "-": "", "'": "'",
                      "and": " and ", "or": " or ", "pipe": " ", "spaces": " ", "space": " ", "zwsp": ""}


def strip_markup_noise(text):
    """Comments, <ref>s, galleries/math and wiki tables carry no breed facts."""
    text = COMMENT_RE.sub("", text)
    text = REF_RE.sub("", text)
    text = DROP_ELEMENT_RE.sub("", text)
    return TABLE_RE.sub("", text)


def protect_links(text):
    """[[a|b]] -> \\x02a\\x01b\\x03, innermost first, so nested File captions work and `|` no longer splits templates."""
    while True:
        new = INNER_LINK_RE.sub(lambda m: "\x02" + m.group(1).replace("|", "\x01") + "\x03", text)
        if new == text:
            return text
        text = new


def split_args(body):
    """Template body -> (name, positional[], named{})."""
    parts = body.split("|")
    name = parts[0].strip().lower().replace("_", " ")
    positional, named = [], {}
    for p in parts[1:]:
        m = NAMED_ARG_RE.match(p)
        if m and "\x02" not in m.group(1):
            named[m.group(1).strip().lower()] = m.group(2).strip()
        else:
            positional.append(p.strip())
    return name, positional, named


def render_convert(positional):
    """{{convert|36|-|44|kg|lb}} -> "36–44 kg"; {{cvt|22|in|cm}} -> "22 in"."""
    if len(positional) >= 4 and positional[1].lower() in RANGE_SEPARATORS:
        return f"{positional[0]}{RANGE_SEPARATORS[positional[1].lower()]}{positional[2]} {positional[3]}"
    if len(positional) >= 2:
        return f"{positional[0]} {positional[1]}"
    return positional[0] if positional else ""


def render_template(body, keep):
    name, positional, named = split_args(body)
    if keep is not None and keep(name):
        return None
    if name in ("convert", "cvt"):
        return render_convert(positional)
    if name in LIST_TEMPLATES:
        return "\n".join(p for p in positional if p)
    if name == "val":
        return " ".join(p for p in (positional[:1] + [named.get("u", ""), named.get("ul", "")]) if p)
    if name in CONSTANT_TEMPLATES:
        return CONSTANT_TEMPLATES[name]
    if name in FIRST_ARG_TEMPLATES or name.startswith("flag"):
        return "" if name == "flagicon" or not positional else positional[0]
    if name in LAST_ARG_TEMPLATES:
        return positional[-1] if positional else ""
    if name.startswith("lang"):   # lang, langx, langr, lang-de ...: the text is the last argument
        return positional[-1] if positional else ""
    if name in ("circa", "c.", "ca."):
        return "c. " + positional[0] if positional else "c."
    if name in ("frac", "fraction"):
        return "/".join(positional)
    return ""   # citations, maintenance tags, navboxes, magic words


def reduce_templates(text, keep=None):
    """Replace innermost {{…}} until none are left. Templates whose name passes `keep` are taken out with their
    already-reduced body and returned as (text_with_markers, [bodies]); a marker is \\x04<n>\\x05."""
    kept = []

    def repl(m):
        out = render_template(m.group(1), keep)
        if out is None:
            kept.append(m.group(1))
            return f"\x04{len(kept) - 1}\x05"
        return out

    while True:
        new = INNER_TEMPLATE_RE.sub(repl, text)
        if new == text:
            return text, kept
        text = new


def render_links(text):
    """Protected links -> their label (File:/Category: links dropped), innermost first."""
    def repl(m):
        target, _, label = m.group(1).partition("\x01")
        if NON_ARTICLE_PREFIX_RE.match(target.strip()):
            return ""
        label = label.split("\x01")[-1]
        return label if label.strip() else target.split("#")[0]

    while True:
        new = PROTECTED_LINK_RE.sub(repl, text)
        if new == text:
            return text
        text = new


def finish_text(text):
    """Rendered wikitext -> plain text lines."""
    text = render_links(text)
    text = EXT_LINK_RE.sub(lambda m: m.group(1) or "", text)
    text = BARE_URL_RE.sub("", text)
    text = BOLD_ITALIC_RE.sub("", text)
    text = BR_RE.sub("\n", text)
    text = TAG_RE.sub("", text)
    text = HEADING_RE.sub(lambda m: m.group(2), text)
    text = MAGIC_WORD_RE.sub("", text)
    text = LIST_MARK_RE.sub("", text)
    text = re.sub(r"\x04\d+\x05|[\x01-\x05]|\{\{|\}\}|\[\[|\]\]", "", text)
    text = html.unescape(text)
    text = SPACES_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r" ([,.;:)])", r"\1", text)
    text = re.sub(r"\(\s*[,;]?\s*\)", "", text)
    return BLANK_LINES_RE.sub("\n", text).strip()


def to_text(wikitext):
    text = protect_links(strip_markup_noise(wikitext))
    text, _ = reduce_templates(text)
    return finish_text(text)


def categories(wikitext):
    out = []
    for c in CATEGORY_RE.findall(COMMENT_RE.sub("", wikitext)):
        c = c.replace("_", " ").strip()
        if c not in out:
            out.append(c)
    return out


def normalise_title(target):
    """Link target -> page title form: underscores, first letter upper-case, no anchor."""
    t = SPACES_RE.sub(" ", html.unescape(target).replace("_", " ").split("#")[0]).strip()
    return t[:1].upper() + t[1:] if t else ""


def protected_link_targets(text):
    """Article targets of protected links (see protect_links), in order."""
    out = []
    for m in PROTECTED_LINK_RE.finditer(text):
        target = m.group(1).split("\x01")[0].strip().lstrip(":")
        if not target or NON_ARTICLE_PREFIX_RE.match(target):
            continue
        t = normalise_title(target)
        if t and t not in out:
            out.append(t)
    return out


def link_targets(wikitext):
    """Article targets of [[…]] links in order, File:/Category:/interwiki dropped."""
    out = []
    for t in LINK_TARGET_RE.findall(COMMENT_RE.sub("", wikitext)):
        if NON_ARTICLE_PREFIX_RE.match(t):
            continue
        t = normalise_title(t)
        if t and t not in out:
            out.append(t)
    return out


def sections(wikitext):
    """[(level, heading, own text up to the next heading of any level)]; the lead is level 0."""
    heads = list(HEADING_RE.finditer(wikitext))
    out = [(0, "", wikitext[:heads[0].start()] if heads else wikitext)]
    for i, m in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(wikitext)
        out.append((len(m.group(1)), finish_text(m.group(2)), wikitext[m.end():stop]))
    return out
