"""Bounded public API work and disk use, independent of radio processing."""
import os
import tempfile
import threading
import time
from collections import OrderedDict
from pathlib import Path


class PublicRequestLimits:
    """Per-peer and global token buckets with a bounded peer table."""
    MAX_PEERS = 2048
    MAX_ACTIVE = 16
    # Burst capacity, refill tokens per second. Cached map tiles remain cheap.
    POLICIES = {'tiles': (256, 10), 'analytics': (12, 0.5), 'api': (60, 4)}

    def __init__(self, clock=time.monotonic, global_capacity=240, global_rate=20):
        self.clock = clock
        self.global_capacity = global_capacity
        self.global_rate = global_rate
        self.peers = OrderedDict()
        self.global_bucket = [float(global_capacity), clock()]
        self.active = 0

    def acquire(self, peer, path):
        if self.active >= self.MAX_ACTIVE:
            return 503
        kind = 'tiles' if path.startswith('/api/map-tiles/') else (
            'analytics' if path.startswith('/api/analytics/') else 'api')
        now = self.clock()
        key = (peer, kind)
        capacity, rate = self.POLICIES[kind]
        bucket = self.peers.pop(key, [float(capacity), now])
        self.peers[key] = bucket
        while len(self.peers) > self.MAX_PEERS:
            self.peers.popitem(last=False)
        for item, cap, refill in ((bucket, capacity, rate), (self.global_bucket, self.global_capacity, self.global_rate)):
            item[0] = min(float(cap), item[0] + max(0, now - item[1]) * refill)
            item[1] = now
        if bucket[0] < 1 or self.global_bucket[0] < 1:
            return 429
        bucket[0] -= 1
        self.global_bucket[0] -= 1
        self.active += 1
        return None

    def release(self):
        self.active -= 1


class TileCacheBudget:
    """Serialize cache commits and evict oldest tiles across all tile sources."""
    SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}

    def __init__(self, root, max_bytes=512 * 1024 * 1024, max_files=10000):
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.max_files = max_files
        self.lock = threading.Lock()
        self.entries = OrderedDict()
        self.size = 0
        self.last_scan = None

    def _scan(self):
        entries = []
        for path in self.root.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in self.SUFFIXES:
                try:
                    stat = path.stat()
                    entries.append((stat.st_mtime, path, stat.st_size))
                except FileNotFoundError:
                    continue
        self.entries = OrderedDict((path, size) for _, path, size in sorted(entries))
        self.size = sum(self.entries.values())
        self.last_scan = time.monotonic()

    def _evict(self):
        victim, size = next(iter(self.entries.items()))
        victim.unlink(missing_ok=True)
        self.entries.pop(victim)
        self.size -= size
        parent = victim.parent
        while parent != self.root and parent.is_relative_to(self.root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def store(self, path, data):
        path = Path(path)
        if not data or len(data) > self.max_bytes:
            return None
        with self.lock:
            if not path.resolve().is_relative_to(self.root.resolve()):
                raise ValueError('Tile path outside cache')
            if self.last_scan is None or time.monotonic() - self.last_scan > 60:
                self._scan()
            previous = self.entries.pop(path, 0)
            self.size -= previous
            if previous:
                path.unlink(missing_ok=True)
            while self.entries and (self.size + len(data) > self.max_bytes or len(self.entries) >= self.max_files):
                self._evict()
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.tile-', suffix='.tmp', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                os.replace(name, path)
            finally:
                Path(name).unlink(missing_ok=True)
            self.entries[path] = len(data)
            self.size += len(data)
            return path
