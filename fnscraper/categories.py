"""Event-category classification and selection.

FestivalNet encodes an event's kind in its detail URL — ``/Art-Shows/``,
``/Craft-Shows/``, ``/Fairs/``, ``/Home-Garden-Shows/`` — which the parser
stores on :attr:`Event.category_slug`.  This module groups those raw slugs
into a small set of vendor-facing categories so both the crawl and the
picker can filter by *what kind of show it is*.

The vendor here works packaged salsa: arts/crafts festivals and expos are
the target, and county/state **fairs are excluded by default** (they draw
carnival/ride crowds, not take-home-jar buyers).  The default is only a
starting point — every category can be turned on or off from the command
line (``--categories``) or interactively in the picker (the ``c`` key).
"""

from __future__ import annotations

from typing import Iterable, NamedTuple


class Category(NamedTuple):
    key: str                    # stable id used on the CLI and in saved config
    label: str                  # human-facing name shown in the picker
    keywords: tuple[str, ...]   # substrings matched (lower-cased) against a slug


# Ordered most-specific first: an event is classified by the FIRST category
# whose keyword appears in its slug.  Order matters — "Food-Festivals" must
# reach FOOD before FESTIVAL, and "Fine-Art-Shows" ARTS before OTHER — so do
# not sort this list.
CATEGORIES: tuple[Category, ...] = (
    Category("arts", "Arts", ("art",)),
    Category("crafts", "Crafts", ("craft",)),
    Category("food", "Food & Drink", ("food", "wine", "beer", "culinary", "taste")),
    Category("farmers-market", "Farmers Markets", ("farmer",)),
    Category("music", "Music", ("music", "concert")),
    Category("holiday", "Holiday Markets", ("holiday", "christmas", "boutique")),
    Category("home-garden", "Home, Garden & Expos",
             ("home", "garden", "trade", "expo", "consumer")),
    Category("fair", "Fairs", ("fair",)),
    Category("festival", "Festivals", ("festival", "fest", "celebration")),
    Category("other", "Other", ()),
)

CATEGORY_BY_KEY: dict[str, Category] = {c.key: c for c in CATEGORIES}

# Categories left out of crawls and the picker unless explicitly re-enabled.
DEFAULT_EXCLUDED: frozenset[str] = frozenset({"fair"})


def classify(category_slug: str) -> Category:
    """Map a raw FestivalNet slug to its vendor-facing :class:`Category`."""
    slug = (category_slug or "").lower()
    for cat in CATEGORIES:
        if any(kw in slug for kw in cat.keywords):
            return cat
    return CATEGORY_BY_KEY["other"]


def category_key(category_slug: str) -> str:
    return classify(category_slug).key


def default_selection() -> set[str]:
    """The categories included when the user hasn't chosen — all but fairs."""
    return {c.key for c in CATEGORIES if c.key not in DEFAULT_EXCLUDED}


def all_keys() -> set[str]:
    return {c.key for c in CATEGORIES}


def normalize_keys(keys: Iterable[str]) -> tuple[set[str], list[str]]:
    """Validate user-supplied category keys.

    Returns ``(valid, unknown)`` where ``valid`` is a set of recognized
    keys and ``unknown`` lists the inputs that matched no category, so the
    caller can warn about typos instead of silently dropping them.
    """
    valid: set[str] = set()
    unknown: list[str] = []
    for raw in keys:
        k = raw.strip().lower()
        if k in CATEGORY_BY_KEY:
            valid.add(k)
        else:
            unknown.append(raw)
    return valid, unknown


def filter_events(events: Iterable, selected: set[str] | None) -> list:
    """Keep events whose category is in ``selected``.

    Works on any object exposing ``category_slug`` (an :class:`Event`) — a
    ``None`` selection means "keep everything".
    """
    if selected is None:
        return list(events)
    return [e for e in events if category_key(e.category_slug) in selected]


def filter_scored(scored: Iterable, selected: set[str] | None) -> list:
    """Category-filter :class:`ScoredEvent` objects (``s.event.category_slug``)."""
    if selected is None:
        return list(scored)
    return [s for s in scored if category_key(s.event.category_slug) in selected]


def present_categories(scored: Iterable) -> list[tuple[str, str, int]]:
    """Categories actually appearing in ``scored``, in canonical order.

    Returns ``(key, label, count)`` tuples for the picker's filter modal so
    it only offers categories the user actually has shows in.
    """
    counts: dict[str, int] = {}
    for s in scored:
        k = category_key(s.event.category_slug)
        counts[k] = counts.get(k, 0) + 1
    return [
        (c.key, c.label, counts[c.key])
        for c in CATEGORIES
        if c.key in counts
    ]
