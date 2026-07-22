"""Parsers for FestivalNet listing and event-detail pages.

The site marks events up with schema.org/Festival microdata, which keeps
parsing stable across cosmetic redesigns.  Detail pages additionally carry
a plain <li><strong>Label:</strong> value list with attendance, exhibitor
count, admission, address, etc.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from .models import Event

log = logging.getLogger(__name__)

SOFT_HYPHEN = "­"

# Values FestivalNet uses to mean "we don't know" / "we won't say".
NULLISH = {"na", "n/a", "none", "tba", "tbd", "unknown", "undisclosed", "", "-"}

# Boilerplate addresses baked into every page; never a real promoter contact.
_JUNK_EMAILS = {"foo@bar.com", "support@festivalnet.com", "info@festivalnet.com"}


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
    """Enrich ``event`` in place with detail-page fields.

    FestivalNet serves two completely different detail layouts: the public
    one (schema.org microdata + a ``<li><strong>Label:</strong>`` list) and,
    to logged-in Pro members, a legacy table of
    ``<font class="font-color">Label:</font>`` cells that carries the booth
    fees, application deadlines and promoter contacts.  Dispatch on
    whichever we actually got so a Pro session isn't silently parsed as if
    it were anonymous.
    """
    if is_member_detail_page(html):
        return parse_member_detail_page(html, event)
    return parse_public_detail_page(html, event)


def is_member_detail_page(html: str) -> bool:
    return "ProMembersSearchFullDetailsTable" in html


def parse_public_detail_page(html: str, event: Event) -> Event:
    """Enrich ``event`` in place from an anonymous detail page."""
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
        elif label in ("show dir.", "show dir", "show director"):
            event.contact_name = value

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


# ---------------------------------------------------------------------------
# Member (Pro) detail pages
#
# Logged-in pages are a legacy 4-column table.  Labels are
# ``<font class="font-color">Label:</font>`` and the value is either the rest
# of the same <td> or the next <td>.  Rows are grouped under centered section
# headers ("Exhibit Booths", "Food Booths...", "Music / Entertainment"), which
# matters because "Deadline" and "How/Where apply" appear once per section.
#
# Email addresses are obfuscated with ``eval(unescape('%hex...'))`` so that
# scrapers reading raw HTML don't see them; we decode that back to real markup
# before parsing.
# ---------------------------------------------------------------------------

_OBFUSCATED_EMAIL_RE = re.compile(
    r"<script[^>]*>\s*eval\(unescape\('([^']*)'\)\)\s*;?\s*</script>",
    re.I | re.S,
)
_FN_WRITE_RE = re.compile(r"FNdocumentWrite\('(.*)'\)\s*;?\s*$", re.S)
_SECTION_HEADERS = {
    "exhibit booths": "exhibit",
    "food booths (eat on site food)": "food",
    "music / entertainment": "music",
}


def deobfuscate_emails(html: str) -> str:
    """Replace ``eval(unescape('%..'))`` blocks with the markup they emit."""

    def repl(match: re.Match) -> str:
        decoded = urllib.parse.unquote(match.group(1))
        inner = _FN_WRITE_RE.search(decoded)
        fragment = inner.group(1) if inner else decoded
        return fragment.replace("\\'", "'")

    return _OBFUSCATED_EMAIL_RE.sub(repl, html)


def _is_nullish(value: str) -> bool:
    return _clean(value).lower().strip(" .") in NULLISH


def _parse_fee(value: str) -> float | None:
    """Budget the top of a quoted fee, None when no figure is given.

    Pro listings quote fees as "$125", "$50-$150", "$600+", or words like
    "Contact"/"na".  Taking the low end of a range would understate the
    cost of every show that quotes one, so use the highest figure shown.
    """
    if not value or "$" not in value:
        return None
    # Anchor on a digit: "[\d,]+" alone happily matches a lone comma, and
    # a listing that reads "$," would then blow up in float().
    amounts = [
        float(m.replace(",", ""))
        for m in re.findall(r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)", value)
    ]
    return max(amounts) if amounts else None


def _first_email(node: Tag) -> str:
    """Pull a real promoter address out of a table cell."""
    for a in node.select('a[href^="mailto:"]'):
        addr = _clean(a["href"][len("mailto:"):].split("?")[0])
        if addr and addr.lower() not in _JUNK_EMAILS:
            return addr
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]{2,}", node.get_text(" ", strip=True))
    if m and m.group(0).lower() not in _JUNK_EMAILS:
        return m.group(0)
    return ""


def _label_of(font: Tag) -> str | None:
    """Normalised label text if this <font> is a field label, else None."""
    classes = font.get("class") or []
    if "font-color" not in classes:
        return None
    text = _clean(font.get_text())
    if not text.endswith(":"):
        return None
    return text[:-1].strip().lower()


def _value_after(font: Tag) -> Tag | None:
    """The node holding a label's value.

    Primary labels sit alone in the row's first cell and their value is the
    *next* ``<td>``.  Secondary labels (marked ``fieldTitleProS``) share a
    cell with their value, so they must never spill into the next cell — an
    empty "Ph.:" would otherwise swallow the "E:" beside it.
    """
    cell = font.find_parent("td")
    if cell is None:
        return None
    # Content following the label inside the same cell.
    tail = [s for s in font.next_siblings if not isinstance(s, str) or s.strip()]
    if tail:
        holder = BeautifulSoup("<td></td>", "html.parser").td
        for node in tail:
            holder.append(node.__copy__() if isinstance(node, Tag) else str(node))
        if _clean(holder.get_text()) or holder.select('a[href^="mailto:"]'):
            return holder
    if "fieldTitleProS" in (font.get("class") or []):
        return None
    return cell.find_next_sibling("td")


def _untruncated_text(node: Tag) -> str:
    """Cell text, restored when the site clipped it with a "…".

    Long values are rendered inside ``truncate_with_ellipsis`` cells with
    the real string kept in a ``title`` attribute (or an href), so a naive
    get_text() yields useless stubs like "northcoastpromo.com/exh…".
    """
    text = _clean(node.get_text(" ", strip=True))
    if "…" not in text:
        return text
    for el in node.find_all(attrs={"title": True}):
        title = _clean(el["title"])
        if title:
            return title
    link = node.select_one("a[href]")
    if link:
        return _clean(link["href"])
    return text


def _member_fields(soup: BeautifulSoup) -> list[tuple[str, str, str, Tag]]:
    """Ordered (section, label, value_text, value_node) for the details table."""
    table = soup.select_one("table.ProMembersSearchFullDetailsTable")
    if table is None:
        return []
    out: list[tuple[str, str, str, Tag]] = []
    section = "header"
    for row in table.select("tr"):
        # The "Quick Connect" popup embeds its own table; visiting its rows
        # (and its labels, via the outer row) would double-count fields and
        # break the director/phone/email run below.
        if row.find_parent("tr") is not None:
            continue
        row_text = _clean(row.get_text()).lower()
        if row_text in _SECTION_HEADERS:
            section = _SECTION_HEADERS[row_text]
            continue
        for font in row.find_all("font"):
            if font.find_parent("table") is not table:
                continue
            label = _label_of(font)
            if label is None:
                continue
            node = _value_after(font)
            if node is None:
                continue
            out.append((section, label, _untruncated_text(node), node))
    return out


_MEMBER_DATE_RANGE_RE = re.compile(
    r"([A-Z][a-z]+)\s+(\d{1,2})\s*(?:-\s*(?:([A-Z][a-z]+)\s+)?(\d{1,2})\s*)?,\s*(\d{4})"
)


def _parse_member_dates(text: str) -> tuple[date | None, date | None]:
    """'September 12 - 13, 2026' / 'October 31 - November 2, 2026' -> dates."""
    m = _MEMBER_DATE_RANGE_RE.search(text)
    if not m:
        return None, None
    start_month, start_day, end_month, end_day, year = m.groups()
    try:
        start = datetime.strptime(
            f"{start_month} {start_day} {year}", "%B %d %Y"
        ).date()
    except ValueError:
        return None, None
    if end_day is None:
        return start, start
    try:
        end = datetime.strptime(
            f"{end_month or start_month} {end_day} {year}", "%B %d %Y"
        ).date()
    except ValueError:
        return start, start
    if end < start:            # range crosses New Year
        end = end.replace(year=end.year + 1)
    return start, end


def _parse_member_header(soup: BeautifulSoup, event: Event) -> None:
    """Name, dates, hours, venue and ZIP from the top block of a Pro page."""
    name_el = soup.select_one('h1[itemprop="name"]')
    if name_el:
        event.name = _clean(name_el.get_text()) or event.name
    header = name_el.find_parent("td") if name_el else None
    if header is None:
        return

    spans = [_clean(s.get_text()) for s in header.find_all("span")]
    for text in spans:
        start, end = _parse_member_dates(text)
        if not start:
            continue
        event.start_date = start
        # Only widen the range.  A header that reads "December 31, 2026 -
        # January 2, 2027" parses as a single day here, and the listing
        # page's end date is the better of the two.
        if end and end > start:
            event.end_date = end
        elif event.end_date is None or event.end_date < start:
            event.end_date = start
        break
    # Hours sit in the span right after the date span, e.g.
    # "Sat 12pm-6pm; Sun 12pm-5pm".
    for text in spans:
        if re.search(r"\d\s*(am|pm)", text, re.I) and not _MEMBER_DATE_RANGE_RE.search(text):
            event.hours_text = text
            break

    # "Granite Hill Camping Resort, Gettysburg, PA 17325"
    for div in header.find_all("div"):
        text = _clean(div.get_text(" ", strip=True))
        zm = re.search(r"\b(\d{5})(?:-\d{4})?\s*$", text)
        if zm and "," in text:
            event.zip_code = zm.group(1)
            venue = text[: text.index(",")].strip()
            if venue and not _is_nullish(venue):
                event.venue = venue
            break

    status = soup.select_one(".event-status")
    if status and "not updated" in _clean(status.get_text()).lower():
        event.stale_listing = True


def parse_member_detail_page(html: str, event: Event) -> Event:
    """Enrich ``event`` in place from a logged-in Pro detail page."""
    soup = BeautifulSoup(deobfuscate_emails(html), "html.parser")
    event.pro_data = True
    _parse_member_header(soup, event)

    # Directors are "<name> Ph.: <phone> E: <email>" triples; remember which
    # one we're inside so the bare "Ph."/"E" labels attach to the right person.
    director: str | None = None
    contacts: dict[str, dict[str, str]] = {}
    main_email = ""

    for section, label, value, node in _member_fields(soup):
        blank = _is_nullish(value)

        if label in ("show director", "exhibit director", "food director"):
            director = label.split()[0]          # show / exhibit / food
            contacts.setdefault(director, {})
            if not blank:
                contacts[director]["name"] = value
            continue
        if label == "ph." and director:
            if not blank:
                contacts[director]["phone"] = value
            continue
        if label == "e" and director:
            email = _first_email(node)
            if email:
                contacts[director]["email"] = email
            continue
        director = None       # any other label ends the director run

        if label == "event address" and not blank:
            event.address = value
        elif label == "attendance #":
            event.attendance = _parse_int(value)
        elif label == "# exhibitors":
            event.exhibitors = _parse_int(value)
        elif label == "juried" and not blank:
            event.juried = value.lower()
        elif label == "admission" and not blank:
            event.admission = value
        elif label == "show promoter" and not blank:
            # The cell also holds the "Quick Connect" popup markup; the
            # promoter's own name is the first link in it.
            link = node.select_one("a[href]")
            name = _clean(link.get_text()) if link else value.split("Quick Connect")[0]
            event.promoter = name.strip(" ^")
        elif label == "main email":
            main_email = _first_email(node) or main_email
        elif label == "web":
            link = node.select_one("a[href]")
            if link:
                event.promoter_website = link["href"]
        elif label == "description" and not blank:
            event.description = value[:600]
        elif label == "food booths":
            event.food_booths = _parse_int(value)
        elif label == "booth fees":
            event.booth_fee_text = value
            event.exhib_fee = _parse_fee(value)
        elif label == "food booth fees":
            event.food_fee = _parse_fee(value)
        elif label == "deadline" and not blank:
            if section == "exhibit":
                event.exhibit_deadline = value
            elif section == "food":
                event.food_deadline = value
        elif label == "how/where apply" and not blank:
            # Exhibit-booth instructions win; food is the fallback.
            if section == "exhibit" or not event.application_info:
                event.application_info = value

    # A packaged-food vendor books through the exhibit director when there is
    # one, then the food director, then whoever runs the show.
    for key in ("exhibit", "show", "food"):
        info = contacts.get(key) or {}
        if not event.contact_name and info.get("name"):
            event.contact_name = info["name"]
        if not event.contact_email and info.get("email"):
            event.contact_email = info["email"]
        if not event.contact_phone and info.get("phone"):
            event.contact_phone = info["phone"]
    event.contact_email = event.contact_email or main_email

    # Keep the legacy free-text field populated so the existing deadline
    # parser / TUI / picker keep working unchanged.
    parts = []
    if event.exhibit_deadline:
        parts.append(f"Art & Craft: {event.exhibit_deadline}")
    if event.food_deadline:
        parts.append(f"Food: {event.food_deadline}")
    if parts:
        event.deadlines = " ".join(parts)
    return event
