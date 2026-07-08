"""Configuration for the FestivalNet profitability scraper.

Every number in the scoring model lives here so it can be tuned as real
sales data accumulates.  Values are deliberately conservative: the goal is
ranking events against each other, not predicting exact dollars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

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
AVG_SALE = 10.0            # average transaction (jar or two of salsa)
JAR_PRICE = 8.0            # retail price of a single jar
UNIT_COST_RATIO = 0.35     # cost of goods sold as fraction of revenue

# Fraction of attendees who buy from a given food-product booth at a
# small event.  Capture falls as events get bigger (more to see, more
# competing vendors), so effective buyers = CAPTURE_RATE * attendance**CAPTURE_EXPONENT.
CAPTURE_RATE = 0.045
CAPTURE_EXPONENT = 0.88

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

# Optional FestivalNet Pro credentials.  When set, the scraper logs in and
# real Exhib./Food fees replace the tier estimates wherever the site
# exposes them.
ENV_USERNAME = "FESTIVALNET_USER"
ENV_PASSWORD = "FESTIVALNET_PASS"


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
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls(**overrides)
        s.username = s.username or os.environ.get(ENV_USERNAME)
        s.password = s.password or os.environ.get(ENV_PASSWORD)
        return s
