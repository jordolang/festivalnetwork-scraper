"""State and province tables for the search rail.

FestivalNet's listing pages are keyed by a hyphenated place name
(``/fairs-festivals/West-Virginia``), while the events it returns carry a
two-letter code, so both spellings are needed: the slug to crawl with and
the code to filter already-loaded results by.
"""

from __future__ import annotations

from typing import NamedTuple


class Place(NamedTuple):
    name: str      # "West Virginia"
    code: str      # "WV"
    slug: str      # "West-Virginia" — the listing-page path segment


def _place(name: str, code: str) -> Place:
    return Place(name, code, name.replace(" ", "-"))


US_STATES: tuple[Place, ...] = tuple(_place(name, code) for name, code in (
    ("Alabama", "AL"), ("Alaska", "AK"), ("Arizona", "AZ"), ("Arkansas", "AR"),
    ("California", "CA"), ("Colorado", "CO"), ("Connecticut", "CT"),
    ("Delaware", "DE"), ("District of Columbia", "DC"), ("Florida", "FL"),
    ("Georgia", "GA"), ("Hawaii", "HI"), ("Idaho", "ID"), ("Illinois", "IL"),
    ("Indiana", "IN"), ("Iowa", "IA"), ("Kansas", "KS"), ("Kentucky", "KY"),
    ("Louisiana", "LA"), ("Maine", "ME"), ("Maryland", "MD"),
    ("Massachusetts", "MA"), ("Michigan", "MI"), ("Minnesota", "MN"),
    ("Mississippi", "MS"), ("Missouri", "MO"), ("Montana", "MT"),
    ("Nebraska", "NE"), ("Nevada", "NV"), ("New Hampshire", "NH"),
    ("New Jersey", "NJ"), ("New Mexico", "NM"), ("New York", "NY"),
    ("North Carolina", "NC"), ("North Dakota", "ND"), ("Ohio", "OH"),
    ("Oklahoma", "OK"), ("Oregon", "OR"), ("Pennsylvania", "PA"),
    ("Rhode Island", "RI"), ("South Carolina", "SC"), ("South Dakota", "SD"),
    ("Tennessee", "TN"), ("Texas", "TX"), ("Utah", "UT"), ("Vermont", "VT"),
    ("Virginia", "VA"), ("Washington", "WA"), ("West Virginia", "WV"),
    ("Wisconsin", "WI"), ("Wyoming", "WY"),
))

CA_PROVINCES: tuple[Place, ...] = tuple(_place(name, code) for name, code in (
    ("Alberta", "AB"), ("British Columbia", "BC"), ("Manitoba", "MB"),
    ("New Brunswick", "NB"), ("Newfoundland and Labrador", "NL"),
    ("Nova Scotia", "NS"), ("Ontario", "ON"), ("Prince Edward Island", "PE"),
    ("Quebec", "QC"), ("Saskatchewan", "SK"),
))

UNITED_STATES = "United States"
CANADA = "Canada"
ALL_COUNTRIES = "All Countries"
COUNTRIES = (ALL_COUNTRIES, UNITED_STATES, CANADA)


def places_for(country: str) -> tuple[Place, ...]:
    if country == UNITED_STATES:
        return US_STATES
    if country == CANADA:
        return CA_PROVINCES
    return US_STATES + CA_PROVINCES


def by_code(code: str) -> Place | None:
    code = (code or "").strip().upper()
    for place in US_STATES + CA_PROVINCES:
        if place.code == code:
            return place
    return None


def by_label(label: str) -> Place | None:
    """Resolve "Ohio (OH)" — what the dropdown shows — back to a Place."""
    label = (label or "").strip()
    if label.endswith(")") and "(" in label:
        return by_code(label[label.rindex("(") + 1:-1])
    for place in US_STATES + CA_PROVINCES:
        if place.name.lower() == label.lower():
            return place
    return None


def label(place: Place) -> str:
    return f"{place.name} ({place.code})"
