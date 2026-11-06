"""Regex-only URL extraction and normalisation."""
import html
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

# href of an <a>, either quote style; the fragment is cut by [^"'#]
HREF_RE = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"'#]+)""", re.IGNORECASE)
LOC_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE | re.DOTALL)
SITEMAP_RE = re.compile(r"<sitemap>.*?<loc>\s*(.*?)\s*</loc>.*?</sitemap>", re.IGNORECASE | re.DOTALL)

SKIP_SCHEMES = ("mailto:", "javascript:", "tel:", "data:")
TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|mc_cid$|mc_eid$|ref$)")


def normalize(url):
    """Lower-case scheme/host, no fragment, no tracking params, no default port; None if malformed."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname.lower() if parts.hostname else ""
    try:
        port = parts.port
    except ValueError:        # e.g. href="https://doi.org:10.18632/..."
        return None
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    path = parts.path or "/"
    return urlunsplit((scheme, host, path, urlencode(query), ""))


def extract_links(html_text, base_url):
    out = []
    for raw in HREF_RE.findall(html_text):
        raw = html.unescape(raw).strip()
        if not raw or raw.lower().startswith(SKIP_SCHEMES):
            continue
        absolute = urljoin(base_url, raw)
        if not absolute.startswith(("http://", "https://")):
            continue
        norm = normalize(absolute)
        if norm:
            out.append(norm)
    return out


def extract_sitemap(xml_text):
    """(nested_sitemaps, page_urls)"""
    nested = [html.unescape(u) for u in SITEMAP_RE.findall(xml_text)]
    nested_set = set(nested)
    pages = [normalize(html.unescape(u)) for u in LOC_RE.findall(xml_text) if html.unescape(u) not in nested_set]
    return nested, [u for u in pages if u]


def same_site(url, domain):
    host = urlsplit(url).hostname or ""
    return host == domain
