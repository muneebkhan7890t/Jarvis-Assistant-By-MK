"""Expiring credentials and bounded rate limits for the local companion."""
from collections import OrderedDict, deque
import time
from urllib.parse import urlsplit

class RateLimiter:
    def __init__(self, limit=60, window=60, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.buckets = OrderedDict()

    def allow(self, key):
        now = self.clock()
        bucket = self.buckets.setdefault(key, deque())
        self.buckets.move_to_end(key)
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()
        if len(self.buckets) > 4096:
            self.buckets.popitem(last=False)
        if len(bucket) >= self.limit:
            return False
        bucket.append(now)
        return True

def same_origin(origin, host):
    if not origin:
        return True  # Native clients have no Origin; bearer authentication still required.
    parsed = urlsplit(origin)
    return parsed.scheme == "https" and parsed.netloc.lower() == host.lower()

def safe_upload_name(raw):
    import re
    from pathlib import PureWindowsPath
    name = str(raw).replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(". ")[:180]
    if not name or PureWindowsPath(name).stem.upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1,10)], *[f"LPT{i}" for i in range(1,10)]}:
        raise ValueError("Invalid upload filename")
    allowed = {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".csv", ".json", ".docx", ".xlsx", ".pptx", ".mp3", ".wav", ".mp4"}
    if PureWindowsPath(name).suffix.lower() not in allowed:
        raise ValueError("Unsupported upload type")
    return name
