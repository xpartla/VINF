"""HTTP GET with identity headers, timeouts, body cap and retry back-off."""
import logging
import time

import requests

from . import config

log = logging.getLogger("fetcher")


class FetchResult:
    __slots__ = ("url", "final_url", "status", "body", "content_type", "encoding", "elapsed_ms", "retries", "error")

    def __init__(self, url):
        self.url = url
        self.final_url = url
        self.status = -1          # -1 = no HTTP answer
        self.body = b""
        self.content_type = ""
        self.encoding = ""
        self.elapsed_ms = 0
        self.retries = 0
        self.error = ""

    @property
    def is_html(self):
        return self.status == 200 and "html" in self.content_type.lower()

    @property
    def is_xml(self):
        ct = self.content_type.lower()
        return self.status == 200 and ("xml" in ct or self.body[:2] == b"\x1f\x8b" or self.body.lstrip()[:5] == b"<?xml")

    def text(self):
        return self.body.decode(self.encoding or "utf-8", errors="replace")


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(config.HEADERS)
        self.session.max_redirects = config.MAX_REDIRECTS
        self.timeout = (config.CONNECT_TIMEOUT, config.READ_TIMEOUT)

    def _once(self, url):
        res = FetchResult(url)
        t0 = time.monotonic()
        try:
            with self.session.get(url, timeout=self.timeout, stream=True, allow_redirects=True) as r:
                res.status = r.status_code
                res.final_url = r.url
                res.content_type = r.headers.get("Content-Type", "")
                res.encoding = r.encoding or ""
                chunks, size = [], 0
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    size += len(chunk)
                    if size > config.MAX_BODY_BYTES:
                        res.error = f"body > {config.MAX_BODY_BYTES} bytes, truncated"
                        break
                    chunks.append(chunk)
                res.body = b"".join(chunks)
                retry_after = r.headers.get("Retry-After")
        except requests.RequestException as e:
            res.error = f"{type(e).__name__}: {e}"[:300]
            retry_after = None
        res.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return res, retry_after

    def get(self, url):
        attempt = 0
        while True:
            res, retry_after = self._once(url)
            res.retries = attempt
            retryable = res.status == -1 or res.status in config.RETRY_STATUSES
            if not retryable or attempt >= len(config.RETRY_BACKOFF):
                return res
            wait = config.RETRY_BACKOFF[attempt]
            if retry_after and retry_after.isdigit():
                wait = max(wait, float(retry_after))
            log.warning("retry %d for %s in %.0fs (status %s %s)", attempt + 1, url, wait, res.status, res.error)
            time.sleep(wait)
            attempt += 1
