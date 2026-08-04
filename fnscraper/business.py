"""Per-business configuration, loaded from ``business.json``.

``config.py`` holds the model's defaults — the numbers this project was
first tuned on (a salsa vendor in Zanesville, Ohio).  Those defaults are
useless to the next business that installs the tool, and nobody who is
not a programmer should have to edit a Python file to fix that.

So: a plain JSON file at the project root, written by the setup wizard
(``python -m fnscraper setup``), overrides the defaults at import time.
No file means the historical defaults, unchanged, so an existing install
keeps working exactly as before.

The mapping is deliberately one-way and explicit — the JSON speaks in
business terms ("what one unit sells for"), the config module speaks in
model terms (``PRICE_LADDER``, ``ORDER_MIX``) — so a typo in the JSON
cannot silently redefine some unrelated constant.  The ``advanced``
block is the escape hatch for anyone who does want to poke a raw
constant.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

BUSINESS_FILE = "business.json"
ENV_BUSINESS_FILE = "FNSCRAPER_BUSINESS"

# Where the model's constants live relative to this file: the package's
# parent is the project root, which is also the install directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# The file itself
# ---------------------------------------------------------------------------

def business_path(root: str | os.PathLike | None = None) -> Path:
    """Path to the active ``business.json``.

    With no ``root``, ``FNSCRAPER_BUSINESS`` selects the file, so a second
    business can be planned from one install without overwriting the
    first one's settings.  An explicit ``root`` always wins: a caller that
    names a directory means that directory, and silently redirecting its
    write to somewhere else would clobber a file it never mentioned.
    """
    if root is not None:
        return Path(root) / BUSINESS_FILE
    override = os.environ.get(ENV_BUSINESS_FILE)
    if override:
        return Path(override).expanduser()
    return PROJECT_ROOT / BUSINESS_FILE


def load(root: str | os.PathLike | None = None) -> dict[str, Any]:
    """Read ``business.json``; ``{}`` when it is missing or unreadable.

    A broken settings file must never take the whole tool down — the
    defaults are always a working configuration, so a parse error is
    reported and skipped rather than raised.
    """
    path = business_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:      # pragma: no cover
        import sys
        print(f"WARNING: ignoring {path}: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict[str, Any], root: str | os.PathLike | None = None) -> Path:
    """Write ``business.json``, pretty-printed for hand-editing."""
    path = business_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def slugify(name: str) -> str:
    """A filesystem-safe token for a business name."""
    out = "".join(c.lower() if c.isalnum() else "-" for c in name)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "business"


# ---------------------------------------------------------------------------
# Applying it to the config module
# ---------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    """A finite number, or None for anything that isn't one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _set(cfg, name: str, value: Any) -> None:
    setattr(cfg, name, value)


def apply(cfg, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Overwrite ``cfg``'s constants from ``data``; returns what was used.

    ``cfg`` is the ``config`` module.  Only keys actually present in the
    file are touched, so a partial file (the wizard skipped a section,
    someone hand-edited one number) leaves everything else at its
    default.
    """
    data = load() if data is None else data
    if not data:
        return {}

    name = data.get("business_name")
    if isinstance(name, str) and name.strip():
        _set(cfg, "BUSINESS_NAME", name.strip())
        _set(cfg, "BUSINESS_SLUG", slugify(name))
        _set(cfg, "BEST_EXPORT_DIR", f"reports/{slugify(name)}")

    _apply_home(cfg, data.get("home"))
    _apply_product(cfg, data.get("product"))
    _apply_travel(cfg, data.get("travel"))
    _apply_planning(cfg, data.get("planning"))

    states = data.get("states")
    if isinstance(states, list) and states:
        _set(cfg, "DEFAULT_STATES", [str(s) for s in states])

    hours = _num(data.get("max_drive_hours"))
    if hours and hours > 0:
        _set(cfg, "MAX_DRIVE_HOURS", hours)

    # Escape hatch: raw constant names, applied last so they win.
    advanced = data.get("advanced")
    if isinstance(advanced, dict):
        for key, value in advanced.items():
            if key.isupper() and hasattr(cfg, key):
                _set(cfg, key, value)

    # Derived values that were computed when the module was imported have
    # to be recomputed now, or they keep quoting the old defaults.
    _set(cfg, "AVG_SALE", cfg.avg_sale())
    return data


def _apply_home(cfg, home: Any) -> None:
    if not isinstance(home, dict):
        return
    lat, lon = _num(home.get("lat")), _num(home.get("lon"))
    if lat is not None and lon is not None:
        _set(cfg, "HOME_LAT", lat)
        _set(cfg, "HOME_LON", lon)
    label = home.get("name")
    if not label:
        city, state = home.get("city"), home.get("state")
        label = f"{city}, {state}" if city and state else None
    if label:
        _set(cfg, "HOME_NAME", str(label))


def _apply_product(cfg, product: Any) -> None:
    """Rebuild the price ladder and order mix from plain business terms."""
    if not isinstance(product, dict):
        return

    unit_name = product.get("unit_name")
    if isinstance(unit_name, str) and unit_name.strip():
        _set(cfg, "UNIT_NAME", unit_name.strip().lower())

    unit_price = _num(product.get("unit_price"))
    unit_cost = _num(product.get("unit_cost"))
    if unit_price and unit_price > 0:
        _set(cfg, "JAR_PRICE", unit_price)
    if unit_cost is not None and unit_cost >= 0:
        _set(cfg, "JAR_COST", unit_cost)
        # A hand-set unit cost must not be overridden by leftover batch
        # economics from the defaults.
        _set(cfg, "BATCH_JARS", None)

    addon_price = _num(product.get("addon_price"))
    addon_cost = _num(product.get("addon_cost"))
    attach = _num(product.get("addon_attach_rate"))
    if addon_price is not None:
        _set(cfg, "CHIPS_PRICE", max(addon_price, 0.0))
    if addon_cost is not None:
        _set(cfg, "CHIPS_COST", max(addon_cost, 0.0))
    if attach is not None:
        _set(cfg, "CHIPS_ATTACH_RATE", min(max(attach, 0.0), 1.0))

    # The deal customers actually buy: N units for $X.  Everything the
    # scoring model needs (average sale, units moved, cost of goods) is
    # derived from this one pair, so they cannot drift apart.
    deal_units = product.get("deal_units")
    deal_price = _num(product.get("deal_price"))
    price = _num(product.get("unit_price")) or cfg.JAR_PRICE
    try:
        deal_units = int(deal_units)
    except (TypeError, ValueError):
        deal_units = None

    if deal_units and deal_units > 0 and deal_price and deal_price > 0:
        ladder = {1: price, deal_units: deal_price}
        _set(cfg, "PRICE_LADDER", sorted(ladder.items()))
        _set(cfg, "ORDER_MIX", {deal_units: 1.0})
        included = bool(product.get("deal_includes_addon"))
        _set(cfg, "BUNDLE_EXTRA_COST",
             {deal_units: cfg.CHIPS_COST} if included else {})
    elif unit_price and unit_price > 0:
        # No deal: every order is a single unit.
        _set(cfg, "PRICE_LADDER", [(1, price)])
        _set(cfg, "ORDER_MIX", {1: 1.0})
        _set(cfg, "BUNDLE_EXTRA_COST", {})


def _apply_travel(cfg, travel: Any) -> None:
    if not isinstance(travel, dict):
        return
    for key, attr, minimum in (
        ("mpg", "MPG", 1.0),
        ("gas_price", "GAS_PRICE", 0.0),
        ("lodging_per_night", "LODGING_PER_NIGHT", 0.0),
        ("meals_per_day", "MEALS_PER_DAY", 0.0),
        ("max_daytrip_hours", "MAX_DAYTRIP_HOURS", 0.0),
    ):
        value = _num(travel.get(key))
        if value is not None and value >= minimum:
            _set(cfg, attr, value)


def _apply_planning(cfg, planning: Any) -> None:
    if not isinstance(planning, dict):
        return
    months = _num(planning.get("months_ahead"))
    if months and months >= 1:
        _set(cfg, "BEST_MONTHS_AHEAD", int(months))
    top = _num(planning.get("top_per_weekend"))
    if top and top >= 1:
        _set(cfg, "BEST_TOP_PER_WEEKEND", int(top))
    jobs = _num(planning.get("parallel_fetches"))
    if jobs and jobs >= 1:
        _set(cfg, "DEFAULT_JOBS", int(jobs))


# ---------------------------------------------------------------------------
# Which states are worth crawling
# ---------------------------------------------------------------------------
# Approximate geographic centre of each state plus a rough radius, so a
# state counts as "in range" when any *part* of it could be — a centroid
# test alone would drop Texas for a vendor in Dallas.  FestivalNet's state
# page slugs are the hyphenated full names.
#
# (slug, abbreviation, centre lat, centre lon, radius in miles)
STATE_TABLE: list[tuple[str, str, float, float, float]] = [
    ("Alabama", "AL", 32.79, -86.83, 150),
    ("Arizona", "AZ", 34.29, -111.66, 200),
    ("Arkansas", "AR", 34.90, -92.44, 150),
    ("California", "CA", 37.15, -119.54, 300),
    ("Colorado", "CO", 38.99, -105.55, 180),
    ("Connecticut", "CT", 41.62, -72.73, 50),
    ("Delaware", "DE", 39.00, -75.50, 50),
    ("District-of-Columbia", "DC", 38.90, -77.02, 10),
    ("Florida", "FL", 28.63, -82.45, 250),
    ("Georgia", "GA", 32.64, -83.44, 170),
    ("Idaho", "ID", 44.35, -114.61, 230),
    ("Illinois", "IL", 40.04, -89.20, 180),
    ("Indiana", "IN", 39.91, -86.28, 130),
    ("Iowa", "IA", 42.07, -93.50, 150),
    ("Kansas", "KS", 38.48, -98.38, 180),
    ("Kentucky", "KY", 37.53, -85.30, 160),
    ("Louisiana", "LA", 31.07, -91.80, 150),
    ("Maine", "ME", 45.37, -69.24, 150),
    ("Maryland", "MD", 39.06, -76.80, 100),
    ("Massachusetts", "MA", 42.26, -71.81, 70),
    ("Michigan", "MI", 44.35, -85.41, 200),
    ("Minnesota", "MN", 46.28, -94.31, 200),
    ("Mississippi", "MS", 32.74, -89.67, 150),
    ("Missouri", "MO", 38.36, -92.48, 170),
    ("Montana", "MT", 47.05, -109.63, 250),
    ("Nebraska", "NE", 41.53, -99.81, 200),
    ("Nevada", "NV", 39.33, -116.63, 230),
    ("New-Hampshire", "NH", 43.68, -71.58, 90),
    ("New-Jersey", "NJ", 40.19, -74.67, 80),
    ("New-Mexico", "NM", 34.42, -106.11, 200),
    ("New-York", "NY", 42.95, -75.53, 180),
    ("North-Carolina", "NC", 35.54, -79.36, 200),
    ("North-Dakota", "ND", 47.45, -100.47, 180),
    ("Ohio", "OH", 40.29, -82.79, 130),
    ("Oklahoma", "OK", 35.59, -97.49, 180),
    ("Oregon", "OR", 43.94, -120.56, 200),
    ("Pennsylvania", "PA", 40.87, -77.80, 160),
    ("Rhode-Island", "RI", 41.68, -71.56, 30),
    ("South-Carolina", "SC", 33.86, -80.90, 130),
    ("South-Dakota", "SD", 44.44, -100.23, 190),
    ("Tennessee", "TN", 35.86, -86.35, 190),
    ("Texas", "TX", 31.48, -99.33, 350),
    ("Utah", "UT", 39.31, -111.68, 180),
    ("Vermont", "VT", 44.07, -72.67, 80),
    ("Virginia", "VA", 37.52, -78.85, 180),
    ("Washington", "WA", 47.38, -120.45, 160),
    ("West-Virginia", "WV", 38.64, -80.62, 120),
    ("Wisconsin", "WI", 44.62, -89.99, 160),
    ("Wyoming", "WY", 42.99, -107.55, 200),
]

STATE_BY_ABBR = {abbr: slug for slug, abbr, *_ in STATE_TABLE}
# Alaska and Hawaii are absent on purpose: nobody drives a booth there.


def states_within(lat: float, lon: float, max_drive_hours: float,
                  circuity: float = 1.25, mph: float = 65.0,
                  home_state: str | None = None) -> list[str]:
    """FestivalNet state slugs whose nearest edge is inside the radius.

    Distance is measured to the state's centre and then discounted by its
    radius, which is crude but errs toward *including* a state — the
    per-event distance filter makes the real cut later, so a state that
    sneaks in only costs a little crawl time, while one wrongly dropped
    hides events forever.
    """
    from .geocode import haversine_miles

    budget_miles = max(max_drive_hours, 0.0) * mph / max(circuity, 0.01)
    picked = []
    for slug, abbr, s_lat, s_lon, radius in STATE_TABLE:
        nearest = max(haversine_miles(lat, lon, s_lat, s_lon) - radius, 0.0)
        if nearest <= budget_miles:
            picked.append(slug)
    home_slug = STATE_BY_ABBR.get((home_state or "").strip().upper())
    if home_slug and home_slug not in picked:
        picked.append(home_slug)
    return sorted(picked)
