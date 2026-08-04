"""Polite HTTP layer: rate limiting, disk cache, optional Pro login."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
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
        workers: int = 1,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.delay = delay
        self.refresh = refresh
        self.cache_ttl = cache_ttl_hours * 3600
        # With N workers we still bound the *aggregate* request rate: the
        # shared throttle spaces successive request starts delay/N apart,
        # so total throughput is ~N/delay req/s no matter how many threads
        # are waiting.  workers=1 => classic one-request-per-`delay`.
        self.workers = max(1, workers)
        self._min_spacing = self.delay / self.workers
        self._last_request = 0.0
        self._throttle_lock = threading.Lock()
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
        """Block until the shared rate limit allows the next request.

        Thread-safe: the lock serialises only the (short) spacing wait, not
        the network call, so N workers overlap their requests while the
        aggregate start-to-start spacing stays at ``self._min_spacing``.
        """
        with self._throttle_lock:
            now = time.time()
            wait = self._min_spacing - (now - self._last_request)
            if wait > 0:
                time.sleep(wait)
                now = time.time()
            self._last_request = now

    def get(self, url: str) -> str:
        """Fetch a URL, using the disk cache when fresh."""
        cached = self._read_cache(url)
        if cached is not None:
            return cached
        self._throttle()
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT)
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
            if resp.is_redirect or resp.is_permanent_redirect:
                return resp.headers.get("Location")
        except requests.RequestException as exc:
            log.debug("redirect probe failed for %s: %s", url, exc)
        return None

    # -- optional Pro login --------------------------------------------
    @staticmethod
    def _extract_csrf_token(html: str) -> str | None:
        """Pull the Laravel CSRF ``_token`` out of the login form."""
        import re
        # Prefer the token inside the form that posts to /login; fall back to
        # any _token on the page (Laravel reuses one per session anyway).
        form = re.search(
            r'<form[^>]*action=["\'][^"\']*login["\'][^>]*>.*?</form>',
            html, re.I | re.S,
        )
        scope = form.group(0) if form else html
        m = re.search(
            r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']', scope, re.I
        ) or re.search(
            r'value=["\']([^"\']+)["\'][^>]*name=["\']_token["\']', scope, re.I
        )
        return m.group(1) if m else None

    def login(self, username: str, password: str) -> bool:
        """Log into FestivalNet so detail pages expose real booth fees.

        The site is a Laravel app: the login form posts an ``email`` +
        ``password`` pair along with a per-session CSRF ``_token`` scraped
        from the login page.  Login responses are never cached.  Returns
        True on apparent success (site stops serving the login form).
        """
        self._throttle()
        login_url = f"{config.BASE_URL}/login"
        # Step 1: GET the login page to seed the session cookie and CSRF token.
        page = self.session.get(login_url, timeout=config.REQUEST_TIMEOUT)
        self._last_request = time.time()
        token = self._extract_csrf_token(page.text)
        if token is None:
            log.warning(
                "could not find CSRF token on login page; "
                "site markup may have changed"
            )

        self._throttle()
        # Step 2: POST credentials with the field names the form actually uses.
        payload = {"email": username, "password": password, "remember": "on"}
        if token is not None:
            payload["_token"] = token
        resp = self.session.post(
            login_url,
            data=payload,
            timeout=config.REQUEST_TIMEOUT,
            allow_redirects=True,
            headers={"Referer": login_url},
        )
        self._last_request = time.time()
        # Success: the response is no longer the login form (Laravel redirects
        # authenticated users away from /login) and shows a member affordance.
        text = resp.text.lower()
        still_login_form = 'name="password"' in text or "name='password'" in text
        self.logged_in = resp.ok and not still_login_form and (
            "logout" in text or "log out" in text or "sign out" in text
        )
        if self.logged_in:
            # Member pages differ from anonymous ones; don't mix caches.
            self.cache_dir = self.cache_dir / "member"
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            log.info("Logged into FestivalNet as %s", username)
        else:
            log.warning("FestivalNet login failed; continuing anonymously")
        return self.logged_in
