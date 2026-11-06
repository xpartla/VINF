"""Regex extraction of expert-advice articles and breed group / list pages."""
import html
import re
from urllib.parse import urlsplit

from .textutil import h1, meta_content, strip_tags, title

ARTICLE_URL_RE = re.compile(r"^https://www\.akc\.org/expert-advice/([a-z0-9-]+)/([a-z0-9-]+)/$")
MAIN_RE = re.compile(r"<main\b[^>]*>(.*?)</main>", re.IGNORECASE | re.DOTALL)
BODY_START_RE = re.compile(r'<div\b[^>]*class="[^"]*content-body__text-long[^"]*"[^>]*>', re.IGNORECASE)
BODY_END_RE = re.compile(r'<div\b[^>]*(?:data-js-component="ebookDownload"|class="page-section"|id="blueconic-download")'
                         r'|</main>', re.IGNORECASE)
DATE_PUBLISHED_RE = re.compile(r'"datePublished":"(\d{4}-\d{2}-\d{2})')
DATE_MODIFIED_RE = re.compile(r'"dateModified":"(\d{4}-\d{2}-\d{2})')
AUTHOR_RE = re.compile(r'"author":\{"@type":"Person","name":"((?:[^"\\]|\\.)*)"')
TAG_META_RE = re.compile(r'<meta\b[^>]*property="article:tag"[^>]*content="([^"]*)"', re.IGNORECASE)
BREED_LINK_RE = re.compile(r'href="(?:https://www\.akc\.org)?/dog-breeds/([a-z0-9-]+)/"')
# group / list slugs under /dog-breeds/ (breeds end in "-dog", lists in "-dogs")
NON_BREED_SLUG_RE = re.compile(r"^(?:page|sporting|hound|working|terrier|toy|non-sporting|herding|miscellaneous-class|"
                               r"foundation-stock-service|best-.*|.*-dog-breeds|.*-dogs)$")
SITE_SUFFIX_RE = re.compile(r"\s*[-–|]\s*American Kennel Club\s*$")


def main_region(html_text):
    m = MAIN_RE.search(html_text)
    return m.group(1) if m else html_text


def article_body(html_text):
    """(body_html, source): long-text container, else <main> up to the widgets, else the page."""
    m = MAIN_RE.search(html_text)
    region, how = (m.group(1), "main") if m else (html_text, "page")
    s = BODY_START_RE.search(region)
    start = s.end() if s else 0
    if s:
        how = "body"
    e = BODY_END_RE.search(region, start)
    return region[start:e.start() if e else len(region)], how


def extract_article(html_text, url):
    m = ARTICLE_URL_RE.match(url)
    body, how = article_body(html_text)
    text = strip_tags(body)
    published = DATE_PUBLISHED_RE.search(html_text)
    modified = DATE_MODIFIED_RE.search(html_text)
    author = AUTHOR_RE.search(html_text)
    return {
        "url": url,
        "category": m.group(1) if m else "",
        "slug": m.group(2) if m else urlsplit(url).path.strip("/").split("/")[-1],
        "title": SITE_SUFFIX_RE.sub("", meta_content(html_text, "og:title") or h1(html_text) or title(html_text)).strip(),
        "description": meta_content(html_text, "description"),
        "published": published.group(1) if published else "",
        "modified": modified.group(1) if modified else "",
        "author": author.group(1).replace("\\/", "/") if author else "",
        "tags": [html.unescape(t).strip() for t in TAG_META_RE.findall(html_text) if t.strip()],
        "body_source": how,
        "n_words": len(text.split()),
        "text": text,
    }


def extract_list_page(html_text, url):
    main = main_region(html_text)
    slugs = []
    for s in BREED_LINK_RE.findall(main):
        if not NON_BREED_SLUG_RE.match(s) and s not in slugs:
            slugs.append(s)
    text = strip_tags(main)
    return {
        "url": url,
        "slug": urlsplit(url).path.strip("/").split("/")[-1] or "dog-breeds",
        "title": SITE_SUFFIX_RE.sub("", title(html_text)).strip(),
        "description": meta_content(html_text, "description"),
        "breeds": slugs,
        "n_words": len(text.split()),
        "text": text,
    }
