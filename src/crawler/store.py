"""Raw page store: one file per URL + one metadata line per fetch; nothing is deleted."""
import hashlib
import json
import logging
import threading
from datetime import datetime, timezone

from . import config

log = logging.getLogger("store")


def url_sha1(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, data_dir=config.DATA_DIR):
        self.raw = data_dir / "raw"
        self.meta = data_dir / "meta"
        self.raw.mkdir(parents=True, exist_ok=True)
        self.meta.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def save(self, site, res, parent_url, depth):
        sha = url_sha1(res.url)
        ext = ".xml" if res.is_xml else ".html"
        path = self.raw / site / sha[:2] / f"{sha}{ext}"
        if res.body:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(res.body)
        meta = {
            "url": res.url,
            "final_url": res.final_url,
            "sha1": sha,
            "site": site,
            "status": res.status,
            "content_type": res.content_type,
            "size": len(res.body),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "elapsed_ms": res.elapsed_ms,
            "retries": res.retries,
            "parent_url": parent_url,
            "depth": depth,
            "encoding": res.encoding,
            "file": str(path.relative_to(self.raw.parent)) if res.body else "",
            "error": res.error,
        }
        with self.lock:
            with open(self.meta / f"{site}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        return meta
