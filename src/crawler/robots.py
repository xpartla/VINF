"""robots.txt cache: fetched with our own User-Agent, parsed by the stdlib."""
import logging
import threading
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from . import config

log = logging.getLogger("robots")


class Robots:
    def __init__(self, fetcher):
        self.fetcher = fetcher
        self.parsers = {}
        self.lock = threading.Lock()

    def _parser(self, url):
        host = urlsplit(url).netloc
        with self.lock:
            if host in self.parsers:
                return self.parsers[host]
        rp = RobotFileParser()
        robots_url = f"https://{host}/robots.txt"
        res = self.fetcher.get(robots_url)
        if res.status == 200 and res.body:
            rp.parse(res.body.decode("utf-8", errors="replace").splitlines())
            log.info("robots.txt loaded for %s (%d bytes)", host, len(res.body))
        else:
            rp.parse([])  # 404 / error -> allow all
            log.info("robots.txt for %s: HTTP %s -> allow all", host, res.status)
        with self.lock:
            self.parsers[host] = rp
        return rp

    def allowed(self, url):
        return self._parser(url).can_fetch(config.USER_AGENT, url)

    def crawl_delay(self, url):
        d = self._parser(url).crawl_delay(config.USER_AGENT)
        return float(d) if d else None
