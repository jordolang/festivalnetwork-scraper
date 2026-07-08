"""Locate, download, and auto-fill vendor applications for chosen shows.

For each imported show this module:

1. Re-fetches its FestivalNet listing and extracts the promoter's website
   (FestivalNet encodes it as a redirect slug like
   ``/https-www-northcoastpromo-com``).
2. Crawls that site shallowly (home page + the most application-looking
   pages) hunting for vendor/exhibitor application documents.
3. Downloads PDF/DOC applications into ``applications/<show>/downloads/``.
4. Auto-fills fillable PDFs from the vendor profile into
   ``applications/<show>/<name>__FILLED.pdf``; flat PDFs and online forms
   get an ``ANSWERS.md`` copy-paste sheet instead.
5. Writes a per-show README and a top-level INDEX.md manifest.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from . import pdf_fill
from .http import Fetcher
from .models import ScoredEvent

log = logging.getLogger(__name__)

STRONG_KEYWORDS = [
    "vendor application", "exhibitor application", "vendor registration",
    "exhibitor registration", "become a vendor", "vendor info",
    "vendor information", "call for vendors", "application",
]
WEAK_KEYWORDS = [
    "vendor", "vendors", "exhibitor", "exhibitors", "apply", "registration",
    "register", "booth", "participate", "get involved", "artist", "crafter",
]
# Things that look like applications but aren't vendor applications.
NEGATIVE_KEYWORDS = [
    "permit", "sponsor", "volunteer", "donat", "employ", "career", "job",
    "ticket", "parking", "press", "scholarship", "pageant", "5k", "raffle",
    "rfp", "bid", "agenda", "minutes",
]
DOWNLOAD_SCORE_THRESHOLD = 8
DOC_EXTENSIONS = (".pdf", ".doc", ".docx")
FORM_HOSTS = (
    "jotform.com", "forms.gle", "docs.google.com", "zapplication.org",
    "eventeny.com", "submittable.com", "formstack.com", "wufoo.com",
    "cognitoforms.com", "typeform.com",
)

MAX_SITES_PER_SHOW = 3
MAX_PAGES_PER_SITE = 6
MAX_DOCS_PER_SHOW = 5

# Domains that a web search returns but that never host the event's own
# vendor application.
SEARCH_JUNK_DOMAINS = (
    "festivalnet.com", "facebook.com", "instagram.com", "twitter.com",
    "x.com", "youtube.com", "linkedin.com", "pinterest.", "reddit.com",
    "tiktok.com", "yelp.com", "tripadvisor.", "wikipedia.org",
    "eventbrite.", "10times.com", "allevents.in", "everfest.com",
    "duckduckgo.com", "bing.com", "google.", "yahoo.", "mapquest.",
    "americantowns.com", "onlyinyourstate.com", "fairsandfestivals.net",
)


@dataclass
class ShowApplications:
    slug: str
    name: str
    listing_url: str
    promoter_sites: list[str] = field(default_factory=list)
    downloaded: list[str] = field(default_factory=list)      # relative paths
    filled: list[str] = field(default_factory=list)
    online_forms: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return slug[:max_len].rstrip("-") or "show"


def show_slug(s: ScoredEvent) -> str:
    e = s.event
    prefix = f"{e.start_date:%Y-%m-%d}" if e.start_date else "undated"
    return f"{prefix}_{e.state or 'XX'}_{slugify(e.name)}"


def decode_fn_link(href: str) -> str | None:
    """Heuristic decode of FestivalNet's ``/https-www-example-com`` slugs."""
    slug = href.strip("/")
    m = re.match(r"(https?)-(.+)$", slug)
    if not m:
        return None
    host = m.group(2).replace("-", ".")
    return f"{m.group(1)}://{host}"


def _score_link(text: str, href: str) -> int:
    blob = f"{text} {href}".lower()
    score = 0
    for kw in STRONG_KEYWORDS:
        if kw in blob:
            score += 10
    for kw in WEAK_KEYWORDS:
        if kw in blob:
            score += 2
    if href.lower().split("?")[0].endswith(DOC_EXTENSIONS):
        score += 5
    for kw in NEGATIVE_KEYWORDS:
        if kw in blob:
            score -= 12
    return score


_STOPWORDS = {"the", "of", "and", "at", "a", "an", "in", "on", "for"}


def _name_tokens(name: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", name.lower())
        if len(t) >= 3 and t not in _STOPWORDS and not t.isdigit()
    }


def _relevance(tokens: set[str], text: str) -> float:
    """Fraction of the event-name tokens present in ``text``."""
    if not tokens:
        return 0.0
    blob = text.lower()
    return sum(1 for t in tokens if t in blob) / len(tokens)


def _is_form_host(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(h in host for h in FORM_HOSTS)


class ApplicationHunter:
    def __init__(self, fetcher: Fetcher, out_dir: str | Path = "applications",
                 profile: dict | None = None, profile_is_real: bool = False,
                 search_fallback: bool = True):
        self.fetcher = fetcher
        self.out_dir = Path(out_dir)
        self.profile = profile or pdf_fill.DEFAULT_PROFILE
        self.profile_is_real = profile_is_real
        self.search_fallback = search_fallback

    # -- promoter site discovery --------------------------------------
    def find_promoter_sites(self, listing_html: str, listing_url: str) -> list[str]:
        soup = BeautifulSoup(listing_html, "html.parser")
        sites: list[str] = []

        for link in soup.select('[itemprop="organizer"] [itemprop="url"]'):
            href = link.get("href") or ""
            if not href:
                continue
            if href.startswith("http") and "festivalnet.com" not in href:
                sites.append(href)
                continue
            # Redirect slug: ask the site where it points, then fall back
            # to heuristic decoding.
            probe = urljoin(listing_url, href)
            target = self.fetcher.resolve_redirect(probe)
            if target and "festivalnet.com" not in target:
                sites.append(target)
            else:
                decoded = decode_fn_link(href)
                if decoded:
                    sites.append(decoded)

        # Any absolute external links in the event body (event's own site).
        for a in soup.select(".event-body a[href^='http']"):
            href = a["href"]
            if "festivalnet.com" not in href and not _is_form_host(href):
                sites.append(href)
            elif _is_form_host(href):
                sites.append(href)

        seen, unique = set(), []
        for url in sites:
            key = urlparse(url).netloc.lower().removeprefix("www.")
            if key and key not in seen:
                seen.add(key)
                unique.append(url)
        return unique[:MAX_SITES_PER_SHOW]

    # -- web-search fallback --------------------------------------------
    def _extract_result_url(self, href: str) -> str | None:
        """Unwrap search-engine redirect links to the destination URL."""
        from urllib.parse import parse_qs, unquote
        import base64

        host = urlparse(href).netloc.lower()
        if "duckduckgo.com" in host and "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            href = unquote(qs.get("uddg", [""])[0])
        elif "bing.com" in host and "/ck/" in urlparse(href).path:
            qs = parse_qs(urlparse(href).query)
            token = qs.get("u", [""])[0]
            if token.startswith("a1"):
                try:
                    padded = token[2:] + "=" * (-len(token[2:]) % 4)
                    href = base64.urlsafe_b64decode(padded).decode()
                except Exception:
                    return None
            else:
                return None
        if not href.startswith("http"):
            return None
        host = urlparse(href).netloc.lower()
        if not host or any(j in host for j in SEARCH_JUNK_DOMAINS):
            return None
        return href

    def _search_provider(self, url: str, selector: str) -> list[tuple[str, str]]:
        """Return (result_url, link_text) pairs from one search engine."""
        try:
            html = self.fetcher.get(url)
        except Exception as exc:
            log.debug("search provider failed (%s): %s", url, exc)
            return []
        soup = BeautifulSoup(html, "html.parser")
        found = []
        for a in soup.select(selector):
            result = self._extract_result_url(a["href"])
            if result:
                found.append((result, a.get_text(" ", strip=True)))
        return found

    def _verify_site(self, url: str, tokens: set[str]) -> bool:
        """Fetch a candidate homepage and confirm it mentions the event."""
        try:
            html = self.fetcher.get(url)
        except Exception:
            return False
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        return _relevance(tokens, text) >= 0.6

    def search_for_site(self, s: ScoredEvent) -> list[str]:
        """Find the event's own website via a web search when the
        FestivalNet listing doesn't expose one publicly.

        Search results are noisy, so candidates must (a) mention most of
        the event's name in their title/URL and (b) actually mention the
        event on the fetched page before they are crawled for
        applications.
        """
        from urllib.parse import quote_plus

        e = s.event
        tokens = _name_tokens(e.name)
        q = quote_plus(f'"{e.name}" {e.city} {e.state} vendor application')
        providers = [
            (f"https://lite.duckduckgo.com/lite/?q={q}", "a[href]"),
            (f"https://www.bing.com/search?q={q}",
             "li.b_algo h2 a[href], li.b_algo a[href]"),
        ]
        results: list[tuple[str, str]] = []
        for url, selector in providers:
            results = self._search_provider(url, selector)
            if results:
                break

        seen: set[str] = set()
        verified: list[str] = []
        for url, title in results:
            key = urlparse(url).netloc.lower().removeprefix("www.")
            if not key or key in seen:
                continue
            seen.add(key)
            if _relevance(tokens, f"{title} {url}") < 0.6:
                continue
            if self._verify_site(url, tokens):
                verified.append(url)
            if len(verified) >= 2 or len(seen) >= 8:
                break
        return verified

    # -- application hunting -------------------------------------------
    def _collect_links(self, html: str, base_url: str) -> list[tuple[int, str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        scored = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            url = urljoin(base_url, href)
            if not url.startswith("http"):
                continue
            text = a.get_text(" ", strip=True)[:120]
            score = _score_link(text, url)
            if score > 0:
                scored.append((score, url, text))
        scored.sort(key=lambda t: -t[0])
        return scored

    def _page_has_vendor_form(self, html: str) -> bool:
        soup = BeautifulSoup(html, "html.parser")
        if not soup.find("form"):
            return False
        text = soup.get_text(" ", strip=True).lower()
        return any(kw in text for kw in STRONG_KEYWORDS)

    def hunt_site(self, site_url: str, result: ShowApplications,
                  show_dir: Path) -> None:
        same_host = urlparse(site_url).netloc.lower().removeprefix("www.")
        to_visit = [site_url]
        visited: set[str] = set()
        pages = 0

        while to_visit and pages < MAX_PAGES_PER_SITE:
            url = to_visit.pop(0)
            norm = url.split("#")[0].rstrip("/")
            if norm in visited:
                continue
            visited.add(norm)

            if _is_form_host(url):
                if url not in result.online_forms:
                    result.online_forms.append(url)
                continue

            try:
                html = self.fetcher.get(url)
            except Exception as exc:
                result.notes.append(f"could not fetch {url}: {exc}")
                continue
            pages += 1

            if pages > 1 and self._page_has_vendor_form(html):
                if url not in result.online_forms:
                    result.online_forms.append(url)

            for score, link, text in self._collect_links(html, url):
                if len(result.downloaded) >= MAX_DOCS_PER_SHOW:
                    return
                path = urlparse(link).path.lower()
                if path.endswith(DOC_EXTENSIONS):
                    if score >= DOWNLOAD_SCORE_THRESHOLD:
                        self._download_doc(link, text, result, show_dir)
                elif _is_form_host(link):
                    if link not in result.online_forms:
                        result.online_forms.append(link)
                elif score >= 10:
                    host = urlparse(link).netloc.lower().removeprefix("www.")
                    if host == same_host and link.split("#")[0].rstrip("/") not in visited:
                        to_visit.append(link)

    def _download_doc(self, url: str, link_text: str,
                      result: ShowApplications, show_dir: Path) -> None:
        filename = Path(urlparse(url).path).name or "application.pdf"
        dest = show_dir / "downloads" / filename
        if dest.exists():
            return
        try:
            data = self.fetcher.get_bytes(url)
        except Exception as exc:
            result.notes.append(f"download failed {url}: {exc}")
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        result.downloaded.append(str(dest.relative_to(self.out_dir)))
        log.info("  downloaded %s (%s)", filename, link_text or url)

    # -- filling ---------------------------------------------------------
    def _fill_downloads(self, result: ShowApplications, show_dir: Path) -> None:
        needs_answer_sheet = bool(result.online_forms)
        for rel in result.downloaded:
            src = self.out_dir / rel
            if src.suffix.lower() != ".pdf":
                result.notes.append(f"{src.name}: not a PDF, fill manually")
                needs_answer_sheet = True
                continue
            dst = show_dir / f"{src.stem}__FILLED.pdf"
            try:
                filled, total = pdf_fill.fill_pdf(src, dst, self.profile)
            except Exception as exc:
                result.notes.append(f"{src.name}: fill failed ({exc})")
                needs_answer_sheet = True
                continue
            if total == 0:
                result.notes.append(f"{src.name}: flat/scanned PDF, no form fields")
                needs_answer_sheet = True
            else:
                result.filled.append(str(dst.relative_to(self.out_dir)))
                result.notes.append(
                    f"{src.name}: filled {filled}/{total} fields"
                )
        if needs_answer_sheet or not result.downloaded:
            pdf_fill.write_answer_sheet(
                show_dir / "ANSWERS.md", self.profile, result.name
            )

    # -- top level ---------------------------------------------------------
    def process_show(self, s: ScoredEvent) -> ShowApplications:
        slug = show_slug(s)
        result = ShowApplications(slug=slug, name=s.event.name,
                                  listing_url=s.event.url)
        show_dir = self.out_dir / slug
        show_dir.mkdir(parents=True, exist_ok=True)
        log.info("hunting applications for %s", s.event.name)

        try:
            listing_html = self.fetcher.get(s.event.url)
        except Exception as exc:
            result.notes.append(f"listing fetch failed: {exc}")
            return result

        result.promoter_sites = self.find_promoter_sites(listing_html, s.event.url)
        if not result.promoter_sites and self.search_fallback:
            result.promoter_sites = self.search_for_site(s)
            if result.promoter_sites:
                result.notes.append(
                    "listing had no public website; found via web search — "
                    "verify it's the right event before applying"
                )
        if not result.promoter_sites:
            result.notes.append(
                "no promoter website found on the public listing "
                "(a FestivalNet Pro login exposes contact/web links)"
            )
        for site in result.promoter_sites:
            self.hunt_site(site, result, show_dir)

        self._fill_downloads(result, show_dir)
        self._write_show_readme(result, s, show_dir)
        return result

    def _write_show_readme(self, r: ShowApplications, s: ScoredEvent,
                           show_dir: Path) -> None:
        e = s.event
        when = f"{e.start_date}" + (f" – {e.end_date}"
                                    if e.end_date and e.end_date != e.start_date else "")
        lines = [
            f"# {r.name}",
            "",
            f"- **When:** {when}",
            f"- **Where:** {e.address or f'{e.city}, {e.state}'}",
            f"- **Listing:** {r.listing_url}",
            f"- **Deadlines:** {e.deadlines or 'see listing'}",
            "",
            "## Promoter sites checked",
            *([f"- {u}" for u in r.promoter_sites] or ["- (none found)"]),
            "",
        ]
        if r.downloaded:
            lines += ["## Downloaded applications",
                      *(f"- `{p}`" for p in r.downloaded), ""]
        if r.filled:
            lines += ["## Auto-filled (REVIEW BEFORE SENDING)",
                      *(f"- `{p}`" for p in r.filled), ""]
        if r.online_forms:
            lines += ["## Online application forms (fill in browser)",
                      *(f"- {u}" for u in r.online_forms), ""]
        if r.notes:
            lines += ["## Notes", *(f"- {n}" for n in r.notes), ""]
        (show_dir / "README.md").write_text("\n".join(lines))

    def run(self, shows: list[ScoredEvent]) -> list[ShowApplications]:
        if not self.profile_is_real:
            log.warning(
                "vendor_profile.json not found — filling with placeholder "
                "example data. Copy vendor_profile.example.json to "
                "vendor_profile.json and edit it."
            )
        results = [self.process_show(s) for s in shows]
        self._write_index(results)
        return results

    def _write_index(self, results: list[ShowApplications]) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        lines = ["# Applications", ""]
        for r in results:
            status = []
            if r.filled:
                status.append(f"{len(r.filled)} auto-filled")
            if r.downloaded:
                status.append(f"{len(r.downloaded)} downloaded")
            if r.online_forms:
                status.append(f"{len(r.online_forms)} online form(s)")
            if not status:
                status.append("nothing found — apply via listing")
            lines.append(f"- [`{r.slug}/`]({r.slug}/README.md) — {r.name}: "
                         + ", ".join(status))
        lines.append("")
        lines.append("> Auto-filled PDFs use vendor_profile.json. "
                     "**Always review before submitting.**")
        (self.out_dir / "INDEX.md").write_text("\n".join(lines))
        manifest = [dataclass_to_dict(r) for r in results]
        (self.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))


def dataclass_to_dict(r: ShowApplications) -> dict:
    import dataclasses
    return dataclasses.asdict(r)
