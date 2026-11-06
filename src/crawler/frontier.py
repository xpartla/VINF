"""Per-site FIFO queues + global seen set, persisted as text files."""
import logging
import threading
from collections import deque

from . import config

log = logging.getLogger("frontier")


class Frontier:
    def __init__(self, site_ids, data_dir=config.DATA_DIR):
        self.dir = data_dir / "frontier"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.queues = {s: deque() for s in site_ids}
        self.seen = set()
        self.lock = threading.Lock()

    def load(self):
        seen_file = self.dir / "seen.txt"
        if seen_file.exists():
            self.seen = set(l.strip() for l in seen_file.read_text(encoding="utf-8").splitlines() if l.strip())
        for site in self.queues:
            qf = self.dir / f"{site}.queue"
            if qf.exists():
                for line in qf.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        url, depth, parent = (line.split("\t") + ["0", ""])[:3]
                        self.queues[site].append((url, int(depth or 0), parent))
        log.info("frontier loaded: %d seen, %s", len(self.seen),
                 {s: len(q) for s, q in self.queues.items()})

    def checkpoint(self):
        with self.lock:
            (self.dir / "seen.txt").write_text("\n".join(sorted(self.seen)) + "\n", encoding="utf-8")
            for site, q in self.queues.items():
                (self.dir / f"{site}.queue").write_text(
                    "".join(f"{u}\t{d}\t{p}\n" for u, d, p in q), encoding="utf-8")
        log.debug("frontier checkpoint written")

    def push(self, site, url, depth, parent=""):
        with self.lock:
            if url in self.seen:
                return False
            self.seen.add(url)
            self.queues[site].append((url, depth, parent))
            return True

    def pop(self, site):
        with self.lock:
            if self.queues[site]:
                return self.queues[site].popleft()
            return None

    def is_empty(self, site):
        with self.lock:
            return not self.queues[site]

    def size(self, site):
        with self.lock:
            return len(self.queues[site])
