#!/usr/bin/env python3
"""HTTP core for scholar.py: cross-process rate limiting, SQLite response
cache, retry/backoff, and the degraded-not-fatal contract.

Cache/TTL and 429-handling patterns adapted from Academic Research Skills
(ARS) v3.17.0 `scripts/verification_cache.py` and its API clients
(c) 2026 Cheng-I Wu, CC BY-NC 4.0 — see NOTICE.md. The SQLite rate-bucket
mechanism (portable replacement for per-process throttles) is new.

Design contract:
- `fetch()` NEVER raises for network/HTTP conditions; it returns a
  FetchResult whose `degraded_reason` is set when the source is unusable.
  A single API outage must never abort a multi-source fan-out.
- Rate pacing is shared across ALL concurrent processes via a `rate_limits`
  table updated under BEGIN IMMEDIATE — N parallel subagents invoking
  scholar.py stay inside each host's budget together.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SCHEMA_VERSION = "1"
GATE_VERSION = "g1"  # bump to invalidate cached verification-relevant bodies

USER_AGENT_BASE = "intensive-research/1.0 (https://github.com/SeffiCohen/Intensive-research)"

# Per-host minimum interval between requests, seconds. Tuple:
# (interval_with_credential, interval_anonymous). The credential is IR_MAILTO
# for polite pools, NCBI_API_KEY for eutils, S2_API_KEY for Semantic Scholar.
RATE_TABLE = {
    "api.openalex.org": (0.15, 1.0),
    "api.crossref.org": (0.5, 1.0),
    "export.arxiv.org": (3.0, 3.0),  # arXiv ToU pacing floor, never lower
    "www.ebi.ac.uk": (0.25, 0.25),
    "eutils.ncbi.nlm.nih.gov": (0.12, 0.35),
    "dblp.org": (1.0, 1.0),
    "api2.openreview.net": (1.0, 1.0),
    "api.unpaywall.org": (0.2, 0.2),
    "api.semanticscholar.org": (1.1, 1.1),
    "opencitations.net": (1.0, 1.0),
    "doaj.org": (1.0, 1.0),
    "api.labs.crossref.org": (1.0, 1.0),
    "api.biorxiv.org": (1.0, 1.0),
}

_ALLOWED_HOSTS = frozenset(RATE_TABLE)

# TTL classes, seconds.
TTL = {
    "search": 7 * 86400,
    "metadata": 30 * 86400,
    "id_lookup": 90 * 86400,
    "negative": 48 * 3600,
    "retraction": 48 * 3600,
    "fulltext": 30 * 86400,
}

_BACKOFF_SECONDS = 2.0
_MAX_RETRIES = 3


def mailto() -> str | None:
    return os.environ.get("IR_MAILTO") or None


def openalex_key() -> str | None:
    """OpenAlex API key (free at openalex.org/settings/api). Required by the
    Feb-2026 OpenAlex credit model for sustained use; requests still work
    keyless at low volume."""
    return os.environ.get("OPENALEX_API_KEY") or os.environ.get("IR_OPENALEX_KEY") or None


def cache_dir() -> str:
    override = os.environ.get("IR_CACHE_DIR")
    if override:
        return override
    xdg = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(xdg, "intensive-research")


def cache_path() -> str:
    return os.path.join(cache_dir(), "scholar.db")


class Cache:
    """SQLite-backed HTTP cache + cross-process rate buckets + retraction DB."""

    def __init__(self, path: str | None = None):
        self.path = path or cache_path()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._conn = sqlite3.connect(self.path, timeout=30)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        c = self._conn
        c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row and row[0] != SCHEMA_VERSION:
            # Never migrate: drop and recreate.
            for table in ("http_cache", "rate_limits", "retractions", "meta"):
                c.execute(f"DROP TABLE IF EXISTS {table}")
            c.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            row = None
        if not row:
            c.execute(
                "INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)",
                (SCHEMA_VERSION,),
            )
        c.execute(
            "CREATE TABLE IF NOT EXISTS http_cache ("
            " key TEXT PRIMARY KEY, url TEXT, status INTEGER, body BLOB,"
            " ttl_class TEXT, retrieved_at REAL)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS rate_limits ("
            " host TEXT PRIMARY KEY, next_ok_at REAL)"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS retractions ("
            " doi TEXT PRIMARY KEY, status TEXT, notice_doi TEXT,"
            " date TEXT, reasons TEXT)"
        )
        c.commit()

    # -- rate buckets ------------------------------------------------------

    def acquire_slot(self, host: str, interval: float) -> None:
        """Reserve the next request slot for `host` across all processes,
        then sleep until it arrives."""
        now = time.time()
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT next_ok_at FROM rate_limits WHERE host=?", (host,)
            ).fetchone()
            next_ok = row[0] if row else now
            slot = max(now, next_ok)
            conn.execute(
                "INSERT OR REPLACE INTO rate_limits VALUES (?, ?)",
                (host, slot + interval),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            slot = now
        wait = slot - now
        if wait > 0:
            time.sleep(min(wait, 30.0))

    def penalize(self, host: str, seconds: float) -> None:
        """Push the host's next slot out after a 429/5xx."""
        now = time.time()
        conn = self._conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT next_ok_at FROM rate_limits WHERE host=?", (host,)
            ).fetchone()
            next_ok = max(row[0] if row else now, now) + seconds
            conn.execute("INSERT OR REPLACE INTO rate_limits VALUES (?, ?)", (host, next_ok))
            conn.commit()
        except Exception:
            conn.rollback()

    # -- http cache --------------------------------------------------------

    @staticmethod
    def _key(url: str, accept: str) -> str:
        return hashlib.sha256(f"{GATE_VERSION}|{accept}|{url}".encode()).hexdigest()

    def get(self, url: str, accept: str, ttl_class: str):
        row = self._conn.execute(
            "SELECT status, body, ttl_class, retrieved_at FROM http_cache WHERE key=?",
            (self._key(url, accept),),
        ).fetchone()
        if not row:
            return None
        status, body, stored_class, retrieved_at = row
        # Negative results always age out on the shorter negative TTL.
        ttl = TTL["negative"] if status >= 400 else TTL.get(ttl_class, TTL["metadata"])
        if time.time() - retrieved_at > ttl:
            return None
        return status, body

    def put(self, url: str, accept: str, status: int, body: bytes, ttl_class: str) -> None:
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?)",
                (self._key(url, accept), url, status, body, ttl_class, time.time()),
            )
            self._conn.commit()
        except Exception:
            pass

    # -- retraction database ----------------------------------------------

    def retraction_lookup(self, doi: str):
        row = self._conn.execute(
            "SELECT status, notice_doi, date, reasons FROM retractions WHERE doi=?",
            (doi.lower(),),
        ).fetchone()
        if not row:
            return None
        return {"status": row[0], "notice_doi": row[1], "date": row[2], "reasons": row[3]}

    def retraction_bulk_upsert(self, rows) -> int:
        n = 0
        cur = self._conn.cursor()
        for doi, status, notice_doi, date, reasons in rows:
            cur.execute(
                "INSERT OR REPLACE INTO retractions VALUES (?, ?, ?, ?, ?)",
                (doi.lower(), status, notice_doi, date, reasons),
            )
            n += 1
        self._conn.commit()
        return n

    def meta_get(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def meta_set(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
        self._conn.commit()

    # -- stats / maintenance ----------------------------------------------

    def stats(self) -> dict:
        c = self._conn
        entries = c.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0]
        retr = c.execute("SELECT COUNT(*) FROM retractions").fetchone()[0]
        size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
        return {
            "path": self.path,
            "http_entries": entries,
            "retraction_records": retr,
            "size_bytes": size,
            "retractionwatch_loaded_at": self.meta_get("retractionwatch_loaded_at"),
        }

    def clear(self) -> None:
        self._conn.execute("DELETE FROM http_cache")
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


class FetchResult:
    __slots__ = ("status", "body", "from_cache", "degraded_reason", "url")

    def __init__(self, status, body=b"", from_cache=False, degraded_reason=None, url=""):
        self.status = status
        self.body = body
        self.from_cache = from_cache
        self.degraded_reason = degraded_reason
        self.url = url

    @property
    def ok(self) -> bool:
        return self.degraded_reason is None and 200 <= self.status < 300

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8", "replace"))
        except Exception:
            return None


_SSL_CONTEXT = None


def _ssl_context():
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context()
    return _SSL_CONTEXT


# Per-process request counters, flushed into the run ledger by scholar.py.
REQUEST_COUNTS: dict = {"requests": {}, "cache_hits": {}}


def fetch(
    cache: Cache,
    url: str,
    *,
    ttl_class: str = "metadata",
    accept: str = "application/json",
    method: str = "GET",
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: int = 30,
    fresh: bool = False,
) -> FetchResult:
    """Rate-limited, cached, retrying fetch. Never raises for network/HTTP
    conditions — inspect `degraded_reason`."""
    host = urllib.parse.urlsplit(url).netloc
    if host not in _ALLOWED_HOSTS:
        return FetchResult(0, degraded_reason=f"host not allowlisted: {host}", url=url)
    if urllib.parse.urlsplit(url).scheme != "https":
        return FetchResult(0, degraded_reason="non-https url refused", url=url)

    cacheable = method == "GET" and data is None
    if cacheable and not fresh:
        hit = cache.get(url, accept, ttl_class)
        if hit is not None:
            REQUEST_COUNTS["cache_hits"][host] = REQUEST_COUNTS["cache_hits"].get(host, 0) + 1
            status, body = hit
            return FetchResult(status, body, from_cache=True, url=url)

    with_cred, anon = RATE_TABLE[host]
    has_cred = bool(
        mailto()
        or (host == "api.openalex.org" and openalex_key())
        or (host == "eutils.ncbi.nlm.nih.gov" and os.environ.get("NCBI_API_KEY"))
        or (host == "api.semanticscholar.org" and os.environ.get("S2_API_KEY"))
    )
    interval = with_cred if has_cred else anon

    # The api_key is appended at request time only — the cache stays keyed on
    # the keyless URL so entries survive key rotation and never store the key.
    request_url = url
    if host == "api.openalex.org" and openalex_key() and "api_key=" not in url:
        sep = "&" if "?" in url else "?"
        request_url = f"{url}{sep}api_key={urllib.parse.quote(openalex_key())}"

    req_headers = {"User-Agent": _user_agent(), "Accept": accept}
    if headers:
        req_headers.update(headers)

    last_reason = "exhausted retries"
    for attempt in range(_MAX_RETRIES + 1):
        cache.acquire_slot(host, interval)
        REQUEST_COUNTS["requests"][host] = REQUEST_COUNTS["requests"].get(host, 0) + 1
        req = urllib.request.Request(request_url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
                body = resp.read()
                status = resp.status
                if cacheable:
                    cache.put(url, accept, status, body, ttl_class)
                return FetchResult(status, body, url=url)
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = e.read()
            except Exception:
                body = b""
            if status == 404:
                # Definitive miss: cacheable negative.
                if cacheable:
                    cache.put(url, accept, status, body, ttl_class)
                return FetchResult(status, body, url=url)
            if status == 429:
                remaining = (e.headers or {}).get("X-RateLimit-Remaining")
                if remaining == "0":
                    cache.penalize(host, 60.0)
                    return FetchResult(status, body, degraded_reason="rate budget exhausted", url=url)
                backoff = _BACKOFF_SECONDS * (2**attempt)
                cache.penalize(host, backoff)
                last_reason = "429 after retries"
                continue
            if 500 <= status < 600:
                cache.penalize(host, _BACKOFF_SECONDS * (2**attempt))
                last_reason = f"server error {status}"
                continue
            # Other 4xx: report as-is, do not retry.
            return FetchResult(status, body, url=url)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last_reason = f"network error: {getattr(e, 'reason', e)}"
            time.sleep(_BACKOFF_SECONDS * (2**attempt) if attempt < _MAX_RETRIES else 0)
            continue
    return FetchResult(0, degraded_reason=last_reason, url=url)


def _user_agent() -> str:
    m = mailto()
    return f"{USER_AGENT_BASE} mailto:{m}" if m else USER_AGENT_BASE


def eprint(*args) -> None:
    print(*args, file=sys.stderr)
