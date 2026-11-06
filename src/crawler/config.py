"""Crawler configuration: identity headers, timeouts, politeness, per-site scope."""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

CONTACT_EMAIL = "xpartla@stuba.sk"
USER_AGENT = f"VINF-DogBreedAdvisor/0.1 (student project, STU Bratislava; mailto:{CONTACT_EMAIL})"

HEADERS = {
    "User-Agent": USER_AGENT,
    "From": CONTACT_EMAIL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    # Accept-Encoding and Connection: keep-alive are set by requests.Session
}

CONNECT_TIMEOUT = 10.0   # seconds
READ_TIMEOUT = 30.0      # seconds between bytes
MAX_BODY_BYTES = 5 * 1024 * 1024   # pages are 40-700 KB
MAX_REDIRECTS = 5
RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_BACKOFF = [5.0, 15.0, 45.0]   # seconds before retry 1..3; Retry-After wins if larger

DEFAULT_DELAY = 2.0      # seconds between requests to one site
DELAY_JITTER = 0.5       # +- seconds
MAX_DELAY = 60.0         # cap of the back-off after 429/503
BACKOFF_REQUESTS = 10    # requests that keep the doubled delay

CHECKPOINT_EVERY = 50    # pages


class Site:
    """Scope of one crawled site."""

    def __init__(self, site_id, domain, seeds, allow, delay=DEFAULT_DELAY, max_pages=None):
        self.id = site_id
        self.domain = domain          # host that links must stay on
        self.seeds = seeds            # sitemap URLs or ordinary pages
        self.allow = re.compile(allow)
        self.delay = delay
        self.max_pages = max_pages


SITES = {
    "akc": Site(
        site_id="akc",
        domain="www.akc.org",
        # breed sitemap + the six article sitemaps
        seeds=["https://www.akc.org/breed-sitemap.xml"]
              + [f"https://www.akc.org/article-sitemap{i}.xml" for i in range(1, 7)],
        # breed pages, breed hub / lists (+ pagination), expert-advice articles
        allow=r"^https://www\.akc\.org/(?:dog-breeds/(?:[a-z0-9-]+/|page/\d+/)?|expert-advice/[a-z0-9-]+/[a-z0-9-]+/)$",
        delay=2.0,
    ),
    # "dogtime": Site("dogtime", "dogtime.com", ["https://dogtime.com/sitemap-cpt-dog-breed.xml"],
    #                 r"^https://dogtime\.com/dog-breeds/[a-z0-9-]+$"),
    # "dogbreedinfo": Site("dogbreedinfo", "www.dogbreedinfo.com", ["https://www.dogbreedinfo.com/abc.htm"],
    #                      r"^https://www\.dogbreedinfo\.com/[a-z0-9]+\.htm$", delay=2.0),
    # "ukc": Site("ukc", "www.ukcdogs.com", ["https://www.ukcdogs.com/sitemap.xml.gz"],
    #             r"^https://www\.ukcdogs\.com/[a-z0-9-]+$"),
    # "kennelclub": Site("kennelclub", "www.thekennelclub.org.uk", ["https://www.royalkennelclub.com/sitemap.xml"],
    #                    r"^https://www\.thekennelclub\.org\.uk/search/breeds-a-to-z/breeds/.+"),
    # "embark": Site("embark", "embarkvet.com", ["https://embarkvet.com/sitemap.xml"],
    #                r"^https://embarkvet\.com/resources/dog-breeds/[a-z0-9-]+/$"),
}
