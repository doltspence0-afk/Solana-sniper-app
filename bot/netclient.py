"""HTTP client: per-host rate limiting, retries with exponential backoff + jitter, Retry-After support,
run-time sleep budget. Never raises on network problems: returns None and records stats."""
import json, random, time, urllib.error, urllib.request
from urllib.parse import urlparse

# Minimum seconds between calls per host. Chosen below documented free limits:
# DexScreener 60/min (docs.dexscreener.com), GeckoTerminal 30/min (apiguide.geckoterminal.com),
# RugCheck: no official figure found; third-party guidance suggests 2-3s gaps.
MIN_GAP = {"api.dexscreener.com": 1.2, "api.rugcheck.xyz": 3.0, "api.geckoterminal.com": 2.5}
RETRY_STATUS = {0, 429, 500, 502, 503, 504}

def _default_opener(url, headers, timeout=15):
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, b"", dict(e.headers or {})
    except Exception:
        return 0, b"", {}

class Client:
    def __init__(self, opener=_default_opener, sleep=time.sleep, clock=time.monotonic, min_gap=None,
                 retries=3, base=1.0, cap=30.0, budget=180.0, jitter=True, max_bytes=5_000_000):
        self.opener, self._sleep, self.clock = opener, sleep, clock
        self.min_gap = dict(MIN_GAP if min_gap is None else min_gap)
        self.retries, self.base, self.cap, self.budget, self.jitter = retries, base, cap, budget, jitter
        self.max_bytes = max_bytes
        self.last, self.slept, self.stats = {}, 0.0, {}

    def _count(self, host, key):
        d = self.stats.setdefault(host, {}); d[key] = d.get(key, 0) + 1

    def _nap(self, s):
        if s <= 0: return True
        if self.slept + s > self.budget: return False
        self.slept += s; self._sleep(s); return True

    def _backoff(self, attempt, retry_after):
        if retry_after is not None:
            return min(self.cap, retry_after)
        d = min(self.cap, self.base * 2 ** attempt)
        return d * (0.5 + random.random() / 2) if self.jitter else d

    def get_json(self, url, headers=None):
        host = urlparse(url).hostname or ""
        hdrs = {"User-Agent": "paper-desk/1.0", "Accept": "application/json"}
        hdrs.update(headers or {})
        for attempt in range(self.retries + 1):
            gap = self.min_gap.get(host, 1.0)
            wait = self.last.get(host, -1e9) + gap - self.clock()
            if not self._nap(wait):
                self._count(host, "budget"); return None
            self.last[host] = self.clock()
            status, body, rh = self.opener(url, hdrs)
            self._count(host, str(status) if status != 200 else "ok")
            if status == 200:
                if len(body) > self.max_bytes: self._count(host, "toobig"); return None
                try: return json.loads(body)
                except ValueError: self._count(host, "badjson"); return None
            if status not in RETRY_STATUS or attempt == self.retries:
                return None
            ra = None
            try: ra = float({k.lower(): v for k, v in rh.items()}.get("retry-after", ""))
            except (TypeError, ValueError): pass
            if not self._nap(self._backoff(attempt, ra)):
                self._count(host, "budget"); return None
        return None
