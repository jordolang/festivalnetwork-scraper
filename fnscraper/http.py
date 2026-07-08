"""Polite HTTP layer: rate limiting, disk cache, optional Pro login."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)


class Fetcher:
    def __init__(
        self,
        cache_dir: str | Path = "data/cache",
        delay: float = config.REQUEST_DELAY_SECONDS,
        refresh: bool = False,
        cache_ttl_hours: float = config.CACHE_TTL_HOURS,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.refresh = refresh
        self.cache_ttl = cache_ttl_hours * 3600
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT
        self.logged_in = False

    # -- caching ------------------------------------------------------
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self.cache_dir / f"{digest}.json"

    def _read_cache(self, url: str) -> str | None:
        if self.refresh:
            return None
        path = self._cache_path(url)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - entry.get("fetched_at", 0) > self.cache_ttl:
            return None
        if entry.get("url") != url:
            return None
        return entry.get("body")

    def _write_cache(self, url: str, body: str) -> None:
        entry = {"url": url, "fetched_at": time.time(), "body": body}
        self._cache_path(url).write_text(json.dumps(entry))

    # -- fetching -----------------------------------------------------
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)

    def get(self, url: str) -> str:
        """Fetch a URL, using the disk cache when fresh."""
        cached = self._read_cache(url)
        if cached is not None:
            return cached
        self._throttle()
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
                self._last_request = time.time()
                if resp.status_code == 200:
                    self._write_cache(url, resp.text)
                    return resp.text
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = 5 * (attempt + 1)
                    log.warning("HTTP %s for %s; retrying in %ss", resp.status_code, url, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                # Non-retryable non-200 (e.g. 202 bot challenge): give up now.
                raise RuntimeError(f"HTTP {resp.status_code} for {url}")
            except requests.RequestException as exc:
                if attempt == 2:
                    raise
                log.warning("Request error for %s (%s); retrying", url, exc)
                time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {url} after retries")

    def get_bytes(self, url: str, max_bytes: int = 30_000_000) -> bytes:
        """Fetch a binary resource (PDF, DOC).  Cached on disk like get()."""
        cache = self._cache_path(url).with_suffix(".bin")
        if not self.refresh and cache.exists():
            return cache.read_bytes()
        self._throttle()
        resp = self.session.get(
            url, timeout=config.REQUEST_TIMEOUT, stream=True
        )
        self._last_request = time.time()
        resp.raise_for_status()
        chunks, size = [], 0
        for chunk in resp.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                raise RuntimeError(f"{url} exceeds {max_bytes} bytes")
            chunks.append(chunk)
        data = b"".join(chunks)
        cache.write_bytes(data)
        return data

    def resolve_redirect(self, url: str) -> str | None:
        """Return the Location a URL redirects to, without following further."""
        self._throttle()
        try:
            resp = self.session.get(
                url, timeout=config.REQUEST_TIMEOUT, allow_redirects=False
            )
            self._last_request = time.time()
            if resp.is_redirect or resp.is_permanent_redirect:
                return resp.headers.get("Location")
        except requests.RequestException as exc:
            log.debug("redirect probe failed for %s: %s", url, exc)
        return None

    # -- optional Pro login --------------------------------------------
    def login(self, username: str, password: str) -> bool:
        """Log into FestivalNet so detail pages expose real booth fees.

        Login responses are never cached.  Returns True on apparent
        success (site sets a member session cookie and stops serving the
        login form).
        """
        self._throttle()
        resp = self.session.post(
            f"{config.BASE_URL}/login",
            data={"username": username, "password": password},
            timeout=config.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        self._last_request = time.time()
        self.logged_in = resp.ok and "logout" in resp.text.lower()
        if self.logged_in:
            # Member pages differ from anonymous ones; don't mix caches.
            self.cache_dir = self.cache_dir / "member"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            log.info("Logged into FestivalNet as %s", username)
        else:
            log.warning("FestivalNet login failed; continuing anonymously")
        return self.logged_in
