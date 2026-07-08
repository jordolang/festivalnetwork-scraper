"""Parsers for FestivalNet listing and event-detail pages.

The site marks events up with schema.org/Festival microdata, which keeps
parsing stable across cosmetic redesigns.  Detail pages additionally carry
a plain <li><strong>Label:</strong> value list with attendance, exhibitor
count, admission, address, etc.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from .models import Event

log = logging.getLogger(__name__)

SOFT_HYPHEN = "­"


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace(SOFT_HYPHEN, "")).strip()


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    """Parse '2,000' -> 2000; 'na'/'undisclosed'/'unknown' -> None."""
    if not value:
        return None
    cleaned = value.replace(",", "").strip()
    m = re.search(r"\d+", cleaned)
    if not m:
        return None
    return int(m.group(0))


def _parse_money(value: str | None) -> float | None:
    if not value:
        return None
    m = re.search(r"\$?\s*([\d,]+(?:\.\d{1,2})?)", value)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


EVENT_URL_RE = re.compile(
    r"festivalnet\.com/(\d+)/([^/]+)/([^/]+)/([^/?#]+)", re.I
)


def parse_event_url(url: str) -> tuple[str, str] | None:
    """Return (event_id, category_slug) from a detail URL, or None."""
    m = EVENT_URL_RE.search(url)
    if not m:
        return None
    return m.group(1), m.group(3)


# ---------------------------------------------------------------------------
# Listing pages: /fairs-festivals/<State>?page=N
# ---------------------------------------------------------------------------

def parse_listing_page(html: str) -> list[Event]:
    """Extract events from one state listing page.

    Sponsored/featured blocks (class ``ad-banner``) are skipped — they are
    out of date order and re-appear in the organic results anyway.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: list[Event] = []
    for block in soup.select("div.festiv-block"):
        classes = block.get("class") or []
        if "ad-banner" in classes:
            continue
        ev = _parse_listing_block(block)
        if ev is not None:
            events.append(ev)
    return events


def _parse_listing_block(block: Tag) -> Event | None:
    link = block.select_one("h2 a[href]")
    if link is None:
        return None
    url = link["href"]
    parsed = parse_event_url(url)
    if parsed is None:
        return None
    event_id, category_slug = parsed

    name_el = block.select_one('[itemprop="name"]')
    name = _clean(name_el.get_text() if name_el else link.get_text())

    ev = Event(event_id=event_id, name=name, url=url, category_slug=category_slug)

    start_meta = block.select_one('meta[itemprop="startDate"]')
    end_meta = block.select_one('meta[itemprop="endDate"]')
    ev.start_date = _parse_iso_date(start_meta["content"] if start_meta else None)
    ev.end_date = _parse_iso_date(end_meta["content"] if end_meta else None)

    loc = block.select_one('[itemprop="location"]')
    if loc:
        city_el = loc.select_one('[itemprop="addressLocality"]')
        state_el = loc.select_one('[itemprop="addressRegion"]')
        venue_el = loc.select_one('[itemprop="name"]')
        ev.city = _clean(city_el.get_text() if city_el else "")
        ev.state = _clean(state_el.get_text() if state_el else "")
        ev.venue = _clean(venue_el.get_text() if venue_el else "").rstrip(",")

    desc_el = block.select_one('[itemprop="description"]')
    if desc_el:
        ev.description = _clean(desc_el.get_text())[:400]

    ev.unconfirmed_date = block.select_one(".unconfirmedDate") is not None
    ev.stale_listing = block.select_one(".notUpdated") is not None
    return ev


def listing_has_next_page(html: str, current_page: int = 1) -> bool:
    """True when the pager links to a page beyond ``current_page``.

    The pager renders numbered links plus a ``>`` arrow, so we inspect
    hrefs rather than link text.
    """
    soup = BeautifulSoup(html, "html.parser")
    pag = soup.select_one(".pagination-section")
    if pag is None:
        return False
    for a in pag.select("a[href]"):
        m = re.search(r"[?&]page=(\d+)", a["href"])
        if m and int(m.group(1)) > current_page:
            return True
    return False


# ---------------------------------------------------------------------------
# Detail pages: /<id>/<City-State>/<Category>/<slug>
# ---------------------------------------------------------------------------

def parse_detail_page(html: str, event: Event) -> Event:
    """Enrich ``event`` in place with detail-page fields."""
    soup = BeautifulSoup(html, "html.parser")

    start_meta = soup.select_one('meta[itemprop="startDate"]')
    end_meta = soup.select_one('meta[itemprop="endDate"]')
    if start_meta:
        event.start_date = _parse_iso_date(start_meta.get("content")) or event.start_date
    if end_meta:
        event.end_date = _parse_iso_date(end_meta.get("content")) or event.end_date

    dates_block = soup.select_one(".eventDatesBlock")
    if dates_block and dates_block.parent:
        hours_span = dates_block.find_next_sibling("span")
        if hours_span:
            event.hours_text = _clean(hours_span.get_text())

    for li in soup.select("li"):
        strong = li.find("strong")
        if not strong:
            continue
        label = _clean(strong.get_text()).rstrip(":").lower()
        value = _clean(li.get_text().replace(strong.get_text(), "", 1))
        if label == "admission":
            event.admission = value
        elif label == "address":
            event.address = value
        elif label == "attendance":
            # "2,000 # Food Booths: na"
            m = re.match(r"([\d,]+|na|undisclosed|unknown)", value, re.I)
            event.attendance = _parse_int(m.group(1)) if m else None
            fb = re.search(r"#\s*Food Booths:\s*([\w,]+)", value, re.I)
            if fb:
                event.food_booths = _parse_int(fb.group(1))
        elif label == "# of exhibitors":
            m = re.match(r"([\d,]+|na|undisclosed|unknown)", value, re.I)
            event.exhibitors = _parse_int(m.group(1)) if m else None
            j = re.search(r"Juried:\s*(\w+)", value, re.I)
            if j:
                event.juried = j.group(1).lower()
        elif label == "deadlines":
            event.deadlines = value
        elif label == "promoter":
            event.promoter = value.strip(" ^")

    desc_el = soup.select_one('[itemprop="description"]')
    if desc_el:
        event.description = _clean(desc_el.get_text())[:600]

    # Member-only fees.  Anonymous pages list bare "Exhib. Fee"/"Food Fee"
    # labels inside the join-to-view block with no dollar value, so these
    # patterns only match for logged-in Pro sessions.
    text = soup.get_text(" ", strip=True).replace(SOFT_HYPHEN, "")
    fee = re.search(r"Exhib\.?\s*Fee:?\s*\$\s*[\d,]+(?:\.\d{1,2})?", text)
    if fee:
        event.exhib_fee = _parse_money(fee.group(0))
    ffee = re.search(r"Food\s*Fee:?\s*\$\s*[\d,]+(?:\.\d{1,2})?", text)
    if ffee:
        event.food_fee = _parse_money(ffee.group(0))

    return event
