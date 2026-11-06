"""Crawler entry point: one worker thread per site, polite scheduling, resumable frontier."""
import argparse
import gzip
import logging
import random
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):  # allow `python src/crawler/main.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crawler import config
from crawler.fetcher import Fetcher
from crawler.frontier import Frontier
from crawler.robots import Robots
from crawler.store import Store
from crawler.urlextract import extract_links, extract_sitemap, same_site

log = logging.getLogger("crawler")


class Worker(threading.Thread):
    def __init__(self, site, frontier, fetcher, robots, store, max_pages, stop_event):
        super().__init__(name=f"worker-{site.id}", daemon=True)
        self.site = site
        self.frontier = frontier
        self.fetcher = fetcher
        self.robots = robots
        self.store = store
        self.max_pages = max_pages
        self.stop = stop_event
        self.pages = 0
        self.last_fetch = 0.0
        self.delay = site.delay
        self.backoff_left = 0
        self.stats = {}

    def _wait_turn(self):
        wait = self.last_fetch + self.delay + random.uniform(-config.DELAY_JITTER, config.DELAY_JITTER) - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _after_response(self, status):
        self.last_fetch = time.monotonic()
        self.stats[status] = self.stats.get(status, 0) + 1
        if status in (429, 503):
            self.delay = min(self.delay * 2, config.MAX_DELAY)
            self.backoff_left = config.BACKOFF_REQUESTS
            log.warning("[%s] %s received, delay now %.1fs", self.site.id, status, self.delay)
        elif self.backoff_left > 0:
            self.backoff_left -= 1
            if self.backoff_left == 0:
                self.delay = self.site.delay

    def _load_seeds(self):
        robots_delay = self.robots.crawl_delay(self.site.seeds[0])
        if robots_delay:
            self.delay = max(self.delay, robots_delay)
            log.info("[%s] robots crawl-delay %.0fs -> delay %.1fs", self.site.id, robots_delay, self.delay)
        pending = list(self.site.seeds)
        while pending and not self.stop.is_set():
            seed = pending.pop(0)
            self._wait_turn()
            res = self.fetcher.get(seed)
            self._after_response(res.status)
            self.store.save(self.site.id, res, parent_url="", depth=0)
            if res.status != 200:
                log.error("[%s] seed %s -> HTTP %s %s", self.site.id, seed, res.status, res.error)
                continue
            body = gzip.decompress(res.body) if res.body[:2] == b"\x1f\x8b" else res.body
            text = body.decode("utf-8", errors="replace")
            if res.is_xml or "<urlset" in text[:2000] or "<sitemapindex" in text[:2000]:
                nested, pages = extract_sitemap(text)
                pending.extend(nested)
                queued = sum(self.frontier.push(self.site.id, u, 1, seed) for u in pages if self._in_scope(u))
                log.info("[%s] sitemap %s: %d urls, %d queued, %d nested", self.site.id, seed, len(pages), queued, len(nested))
            else:
                self.frontier.push(self.site.id, seed, 0)
                self._handle_links(res, depth=0)

    def _in_scope(self, url):
        return same_site(url, self.site.domain) and bool(self.site.allow.search(url))

    def _handle_links(self, res, depth):
        if not res.is_html:
            return 0
        try:
            links = extract_links(res.text(), res.final_url)
        except Exception as e:    # one odd link must not stop the crawl
            log.warning("[%s] link extraction failed on %s: %s", self.site.id, res.final_url, e)
            return 0
        queued = sum(self.frontier.push(self.site.id, u, depth + 1, res.final_url) for u in links if self._in_scope(u))
        return queued

    def run(self):
        try:
            if self.frontier.is_empty(self.site.id):
                self._load_seeds()
            while not self.stop.is_set():
                if self.max_pages is not None and self.pages >= self.max_pages:
                    log.info("[%s] max pages %d reached", self.site.id, self.max_pages)
                    break
                item = self.frontier.pop(self.site.id)
                if item is None:
                    log.info("[%s] frontier empty", self.site.id)
                    break
                url, depth, parent = item
                if not self.robots.allowed(url):
                    log.info("[%s] robots disallow %s", self.site.id, url)
                    continue
                self._wait_turn()
                res = self.fetcher.get(url)
                self._after_response(res.status)
                self.store.save(self.site.id, res, parent_url=parent, depth=depth)
                self.pages += 1
                queued = self._handle_links(res, depth)
                log.info("[%s] %d/%s %s %s %dB %dms +%d queued (%d left)", self.site.id, self.pages,
                         self.max_pages or "inf", res.status, url, len(res.body), res.elapsed_ms, queued,
                         self.frontier.size(self.site.id))
                if self.pages % config.CHECKPOINT_EVERY == 0:
                    self.frontier.checkpoint()
        except Exception:
            log.exception("[%s] worker crashed", self.site.id)


def setup_logging(data_dir):
    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(threadName)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt,
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(data_dir / "logs" / "crawl.log", encoding="utf-8")])


def main(argv=None):
    ap = argparse.ArgumentParser(description="VINF dog-breed crawler")
    ap.add_argument("--site", action="append", choices=sorted(config.SITES), help="site id(s) to crawl; default: all")
    ap.add_argument("--max-pages", type=int, default=None, help="stop each site after this many pages")
    ap.add_argument("--resume", action="store_true", help="continue from the saved frontier instead of re-seeding")
    args = ap.parse_args(argv)

    setup_logging(config.DATA_DIR)
    sites = [config.SITES[s] for s in (args.site or sorted(config.SITES))]
    frontier = Frontier([s.id for s in sites])
    if args.resume:
        frontier.load()
    fetcher = Fetcher()
    robots = Robots(fetcher)
    store = Store()
    stop = threading.Event()
    workers = [Worker(s, frontier, fetcher, robots, store, args.max_pages, stop) for s in sites]

    t0 = time.monotonic()
    for w in workers:
        w.start()
    try:
        while any(w.is_alive() for w in workers):
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.warning("interrupted, stopping workers and saving frontier")
        stop.set()
        for w in workers:
            w.join(timeout=config.READ_TIMEOUT + 5)
    finally:
        frontier.checkpoint()

    elapsed = time.monotonic() - t0
    print(f"\n=== crawl finished in {elapsed:.0f}s ===")
    for w in workers:
        print(f"{w.site.id}: {w.pages} pages, statuses {dict(sorted(w.stats.items()))}, {frontier.size(w.site.id)} URLs left in frontier")


if __name__ == "__main__":
    main()
