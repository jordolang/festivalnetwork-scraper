"""Configuration for the FestivalNet profitability scraper.

Every number in the scoring model lives here so it can be tuned as real
sales data accumulates.  Values are deliberately conservative: the goal is
ranking events against each other, not predicting exact dollars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://festivalnet.com"

# Home base: Zanesville, Ohio
HOME_NAME = "Zanesville, OH"
HOME_LAT = 39.9403
HOME_LON = -82.0132

# Hard travel limit requested: 10 hours of driving, one way.
MAX_DRIVE_HOURS = 10.0

# Straight-line miles are converted to road miles with a circuity factor
# (US road networks average ~1.2-1.3x the great-circle distance), then to
# hours at an average long-haul speed that mixes interstate and surface
# roads.
ROAD_CIRCUITY = 1.25
AVG_MPH = 58.0

# States whose events can plausibly fall inside a 10 h drive of
# Zanesville.  The distance filter makes the final cut; this list just
# bounds the crawl.  FestivalNet state-page slugs use hyphenated names.
DEFAULT_STATES = [
    "Ohio",
    "West-Virginia",
    "Pennsylvania",
    "Kentucky",
    "Indiana",
    "Michigan",
    "Virginia",
    "Maryland",
    "Delaware",
    "New-Jersey",
    "New-York",
    "Tennessee",
    "Illinois",
    "North-Carolina",
    "South-Carolina",
    "Wisconsin",
    "Missouri",
    "Georgia",
    "Connecticut",
    "District-of-Columbia",
]

# ---------------------------------------------------------------------------
# Vehicle / trip cost model (out-of-pocket dollars)
# ---------------------------------------------------------------------------
MPG = 20.0                 # loaded van/truck pulling product
GAS_PRICE = 3.30           # $/gallon
LODGING_PER_NIGHT = 110.0  # modest hotel
MEALS_PER_DAY = 35.0       # per diem on the road
# One-way drives longer than this require a hotel the night before each
# show day (you can't set up a booth at 7am after a 6-hour drive).
MAX_DAYTRIP_HOURS = 2.5

# ---------------------------------------------------------------------------
# Revenue model for a salsa vendor
# ---------------------------------------------------------------------------
JAR_PRICE = 10.0           # a single jar, bought on its own

# The deals actually offered at the booth: (jars, price).  These matter
# because customers buy *packages*, not jars — the $25 average order is the
# 3-for-$25 deal, so it moves three jars, not "$25 worth" of them.  Dividing
# revenue by the single-jar price would undercount every package sold and so
# undercount the salsa consumed to earn it.
PRICE_LADDER = [
    (1, 10.0),
    (3, 25.0),
    (4, 32.0),
    (5, 40.0),             # 5 jars + a bag of chips
    (12, 80.0),            # a full case
]

# Tortilla chips.  At $3.00 over a $1.00 bag these carry a 67% margin —
# better than any salsa deal on the ladder, the best-earning thing at the
# booth per dollar of stock.  Worth remembering that the 5-jar deal hands
# a bag over for nothing: it costs $1.00 and forgoes $3.00 of chip sales.
CHIPS_PRICE = 3.00
CHIPS_COST = 1.00

# Non-salsa goods bundled into a deal, keyed by the deal's jar count.
BUNDLE_EXTRA_COST = {5: CHIPS_COST}

# Share of orders that also take a bag of chips at the counter, over and
# above anything the deal already includes.  1 in 8, from the vendor's own
# read of the booth — a working estimate, not till data, so treat the chip
# line as the softest number in the model.  Each point of attach rate is
# worth $2.00 of margin per hundred orders.
CHIPS_ATTACH_RATE = 0.125      # 1 in 8

# How the day's orders split across the ladder.  Until there is real till
# data, the honest default is the stated average: every order is the
# 3-for-$25 deal.  Weights are normalised, so a richer mix drawn from real
# receipts can simply be dropped in, e.g.
#     ORDER_MIX = {1: 0.30, 3: 0.45, 4: 0.10, 5: 0.10, 12: 0.05}
ORDER_MIX = {3: 1.0}


def _ladder_price(jars: int) -> float:
    for count, price in PRICE_LADDER:
        if count == jars:
            return price
    raise KeyError(f"no deal on the price ladder sells {jars} jars")


def _mix() -> list[tuple[int, float, float]]:
    """(jars, price, share) for each deal, shares normalised to 1."""
    total = sum(ORDER_MIX.values())
    if total <= 0:
        raise ValueError("ORDER_MIX must have at least one positive weight")
    return [
        (jars, _ladder_price(jars), weight / total)
        for jars, weight in ORDER_MIX.items()
    ]


def avg_sale() -> float:
    """Average dollars per transaction, derived from the deal mix."""
    deals = sum(price * share for _, price, share in _mix())
    return deals + CHIPS_ATTACH_RATE * CHIPS_PRICE


def jars_per_order() -> float:
    """Average jars per transaction, derived from the deal mix."""
    return sum(jars * share for jars, _, share in _mix())


def cogs_per_order() -> float:
    """Cost of goods behind one average order, bundled extras included."""
    deals = sum(
        (jars * jar_cost() + BUNDLE_EXTRA_COST.get(jars, 0.0)) * share
        for jars, _, share in _mix()
    )
    return deals + CHIPS_ATTACH_RATE * CHIPS_COST


# Kept as a module constant for readability in reports.  Derived, not typed
# in, so it can never drift out of step with the ladder above.
AVG_SALE = avg_sale()

# Cost of goods, per jar.  A batch runs about $1,500 of ingredients plus
# about $1,000 of jars and lids, and the true unit cost is known to fall
# between $2.50 and $3.50.  The model uses the top of that band: when the
# question is "does this show pay?", overstating cost is the safe direction.
#
# This is deliberately a cost *per jar* and not a percentage of revenue.
# COGS does not move when the shelf price moves — raising JAR_PRICE to $12
# would, under a percentage, silently invent 20% more ingredient cost.
JAR_COST = 3.50
JAR_COST_RANGE = (2.50, 3.50)      # for sensitivity checks

# Batch economics, for deriving JAR_COST once the yield is known.  Set
# BATCH_JARS to the jars a single batch actually fills and jar_cost() uses
# it instead of the flat figure above.  ($2,500 / 715 jars = $3.50;
# $2,500 / 1,000 jars = $2.50 — so the yield is somewhere in that range.)
BATCH_INGREDIENT_COST = 1_500.0
BATCH_PACKAGING_COST = 1_000.0     # jars and lids
BATCH_JARS: int | None = None      # None -> use JAR_COST


def jar_cost() -> float:
    """Cost to produce one jar, derived from batch yield when it is known."""
    if BATCH_JARS:
        return (BATCH_INGREDIENT_COST + BATCH_PACKAGING_COST) / BATCH_JARS
    return JAR_COST

# Fraction of attendees who buy from the booth.  The house rule is
# "roughly 1 sale per 40 visitors, or better", so the baseline capture is
# 1/40 = 0.025 and scales linearly with attendance (exponent 1.0).
# Demand multipliers (category fit, competition, admission, data quality)
# move the real number up or down from there.
CAPTURE_RATE = 0.025               # 1 buyer per 40 attendees
CAPTURE_EXPONENT = 1.0             # linear in attendance

# "or better": after the multipliers are applied, never model a worse
# conversion than 1-in-40 of the gate.  Set to None to let a bad category
# fit / crowded field drag the estimate below the floor.
MIN_CAPTURE_RATE = 0.025

# One booth can only ring up so many sales in a day, no matter how big
# the crowd — this caps mega-event projections at physical reality.
MAX_DAILY_TRANSACTIONS = 150

# Exhibitor competition: buyers get divided across booths.  An event with
# few exhibitors per 1000 attendees is better for each vendor.
IDEAL_ATTENDEES_PER_EXHIBITOR = 150.0

# How well each FestivalNet category fits a packaged-salsa booth.
# Category slugs come from the event URL (e.g. /Art-Shows/).
CATEGORY_FIT = {
    "food": 1.20,          # food festivals: buyers came hungry
    "farmers-market": 1.15,
    "craft": 1.00,         # craft shows: classic packaged-food fit
    "art": 0.85,           # fine-art buyers browse, still snack
    "fair": 1.10,          # county fairs, street fairs
    "festival": 1.05,      # general festivals
    "music": 0.90,         # music crowds buy food, less take-home
    "home": 0.80,          # home & garden expos
    "holiday": 1.05,       # holiday markets: gift jars sell
    "other": 0.90,
}

# Free-admission events pull bigger, more casual crowds per stated
# attendance number; gated events under-deliver walk-bys.
ADMISSION_FREE_BONUS = 1.10
ADMISSION_PAID_PENALTY = 0.95

# ---------------------------------------------------------------------------
# Booth-fee estimation (used when the real fee is unavailable).
# Tiers keyed by attendance; value is (craft/product booth fee estimate).
# FestivalNet hides exact fees behind Pro membership; these tiers reflect
# typical Midwest/East fees for a packaged-food (non-concession) booth.
# ---------------------------------------------------------------------------
FEE_TIERS = [
    (1_000, 75.0),
    (5_000, 150.0),
    (15_000, 275.0),
    (50_000, 450.0),
    (float("inf"), 750.0),
]
# Events that explicitly host food booths often charge food vendors more.
FOOD_FEE_MULTIPLIER = 1.4
DEFAULT_ATTENDANCE = 1_500   # when the listing says "na"/"undisclosed"
DEFAULT_EXHIBITORS = 40

# Penalty multipliers for data-quality flags.
UNCONFIRMED_DATE_PENALTY = 0.85
STALE_LISTING_PENALTY = 0.90

# ---------------------------------------------------------------------------
# "Best weekends" booking plan (fnscraper best)
# ---------------------------------------------------------------------------
# A show only earns a slot if it actually runs on a weekend day.  Mon/Tue
# are dead for a retail booth, so a show that runs *only* Mon-Tue is cut.
# Weekday numbers are Python's: Mon=0 .. Sun=6.
BOOKABLE_WEEKDAYS = {2, 3, 4, 5, 6}          # Wed-Sun
PRIME_WEEKDAYS = {4, 5, 6}                   # Fri/Sat/Sun — the money days

# Multiplier applied to the ranking score for how much of the show lands on
# prime days.  A Fri-Sun show keeps its full score; a Wed-Thu-only show is
# ranked as if it were worth ~30% less, so it only wins a slot when nothing
# better is available that weekend.
PRIME_WEEKEND_BONUS = 1.00
OFF_WEEKEND_PENALTY = 0.70

BEST_MONTHS_AHEAD = 3          # planning horizon
BEST_TOP_PER_WEEKEND = 5       # shows per weekend in the plan
BEST_EXPORT_DIR = "reports/josemadridsalsa"

# ---------------------------------------------------------------------------
# Crawling behavior
# ---------------------------------------------------------------------------
USER_AGENT = (
    "festivalnetwork-scraper/1.0 (personal vendor research; "
    "+https://github.com/jordolang/festivalnetwork-scraper)"
)
REQUEST_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT = 30
MAX_PAGES_PER_STATE = 40      # safety valve
CACHE_TTL_HOURS = 20          # re-use fetched pages within a day

# How many FestivalNet pages to fetch in parallel.  The throttle keeps the
# *aggregate* request rate polite (delay / jobs seconds between requests),
# so more jobs = faster crawl at a proportionally higher steady rate.
# 1 restores the old strictly-sequential, one-request-per-1.5s behaviour.
DEFAULT_JOBS = 4

# Optional FestivalNet Pro credentials.  When set, the scraper logs in and
# real Exhib./Food fees replace the tier estimates wherever the site
# exposes them.
ENV_USERNAME = "FESTIVALNET_USER"
ENV_PASSWORD = "FESTIVALNET_PASS"


def load_dotenv(path: str | os.PathLike | None = None) -> None:
    """Populate os.environ from a .env file if present.

    Minimal, dependency-free KEY=VALUE parser so credentials placed in a
    (gitignored) .env are picked up on every run without the user having to
    `export` them each session.  Existing environment variables win, so a
    real shell export always overrides the file.
    """
    if path is None:
        # Project root is one directory up from this package.
        path = Path(__file__).resolve().parent.parent / ".env"
    path = Path(path)
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Settings:
    """Runtime settings assembled from defaults + CLI flags."""

    states: list[str] = field(default_factory=lambda: list(DEFAULT_STATES))
    weeks_ahead: int = 8
    max_drive_hours: float = MAX_DRIVE_HOURS
    top_per_weekend: int = 5
    output_dir: str = "reports"
    cache_dir: str = "data/cache"
    geocode_cache: str = "data/geocode_cache.json"
    refresh: bool = False              # ignore HTTP cache
    max_pages_per_state: int = MAX_PAGES_PER_STATE
    jobs: int = DEFAULT_JOBS           # parallel FestivalNet fetches
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        load_dotenv()
        s = cls(**overrides)
        s.username = s.username or os.environ.get(ENV_USERNAME)
        s.password = s.password or os.environ.get(ENV_PASSWORD)
        return s
