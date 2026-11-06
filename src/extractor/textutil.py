"""Regex helpers: HTML -> text, <title>/<meta>/<link> values, JSON string unescaping."""
import html
import re

# elements that hold menus and widgets, never content
_DROP_ELEMENT_RE = re.compile(r"<(head|script|style|noscript|template|svg|iframe|select|form|nav|footer)\b[^>]*>.*?</\1\s*>",
                              re.IGNORECASE | re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_TAG_RE = re.compile(
    r"</?(?:p|div|br|hr|li|ul|ol|dl|dt|dd|h[1-6]|tr|td|th|table|thead|tbody|section|article|aside|header|footer|nav|"
    r"blockquote|figure|figcaption|pre|form|fieldset|address|main)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"[ \t\r\f\v ]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")

TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def strip_tags(html_text):
    text = _COMMENT_RE.sub(" ", html_text)
    text = _DROP_ELEMENT_RE.sub(" ", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _SPACES_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES_RE.sub("\n", text)
    return text.strip()


def collapse_ws(text):
    return _SPACES_RE.sub(" ", text.replace("\n", " ")).strip()


def title(html_text):
    m = TITLE_RE.search(html_text)
    return collapse_ws(html.unescape(_TAG_RE.sub("", m.group(1)))) if m else ""


def h1(html_text):
    m = H1_RE.search(html_text)
    return collapse_ws(html.unescape(_TAG_RE.sub("", m.group(1)))) if m else ""


def meta_content(html_text, name):
    """<meta name|property=... content=...> in either attribute order."""
    pat = re.escape(name)
    m = re.search(r'<meta\b[^>]*?\b(?:name|property)\s*=\s*["\']%s["\'][^>]*?\bcontent\s*=\s*["\']([^"\']*)' % pat,
                  html_text, re.IGNORECASE)
    if not m:
        m = re.search(r'<meta\b[^>]*?\bcontent\s*=\s*["\']([^"\']*)["\'][^>]*?\b(?:name|property)\s*=\s*["\']%s["\']' % pat,
                      html_text, re.IGNORECASE)
    return html.unescape(m.group(1)).strip() if m else ""


_JSON_ESCAPE_RE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|(.))", re.DOTALL)
_JSON_SIMPLE = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def json_unescape(s):
    """JSON string escapes -> characters, without a JSON parser."""
    def repl(m):
        if m.group(1):
            return chr(int(m.group(1), 16))
        return _JSON_SIMPLE.get(m.group(2), m.group(2))
    return _JSON_ESCAPE_RE.sub(repl, s)


def json_text(s):
    return strip_tags(json_unescape(s)) if s else ""


CANONICAL_RE = re.compile(r'<link\b[^>]*?\brel\s*=\s*["\']canonical["\'][^>]*?\bhref\s*=\s*["\']([^"\']*)', re.IGNORECASE)
CANONICAL_REV_RE = re.compile(r'<link\b[^>]*?\bhref\s*=\s*["\']([^"\']*)["\'][^>]*?\brel\s*=\s*["\']canonical["\']', re.IGNORECASE)
BODY_CLASS_RE = re.compile(r'<body\b[^>]*?\bclass\s*=\s*["\']([^"\']*)', re.IGNORECASE)


def canonical_url(html_text):
    """href of <link rel="canonical">, either attribute order."""
    m = CANONICAL_RE.search(html_text) or CANONICAL_REV_RE.search(html_text)
    return html.unescape(m.group(1)).strip() if m else ""


def body_classes(html_text):
    """WordPress puts the page kind here ("single", "archive")."""
    m = BODY_CLASS_RE.search(html_text)
    return m.group(1).split() if m else []
