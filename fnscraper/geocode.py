"""Geocoding with a persistent cache.

Order of preference for each event:
1. ZIP code from the street address via zippopotam.us (free, keyless, fast)
2. City + state via Nominatim (OpenStreetMap; 1 req/sec policy respected)
3. State centroid fallback (marked approximate)

Every successful lookup is cached on disk so repeat runs make no network
calls.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path

import requests

from . import config

log = logging.getLogger(__name__)

STATE_CENTROIDS = {
    "OH": (40.29, -82.79), "WV": (38.49, -80.95), "PA": (40.88, -77.80),
    "KY": (37.67, -84.67), "IN": (39.85, -86.26), "MI": (43.33, -84.54),
    "VA": (37.77, -78.17), "MD": (39.06, -76.80), "DE": (39.32, -75.51),
    "NJ": (40.30, -74.52), "NY": (42.75, -75.47), "TN": (35.75, -86.70),
    "IL": (40.35, -88.99), "NC": (35.63, -79.81), "SC": (33.86, -80.95),
    "WI": (44.27, -89.62), "MO": (38.46, -92.29), "GA": (33.04, -83.64),
    "CT": (41.60, -72.76), "DC": (38.90, -77.03),
}

ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\s*$")


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Geocoder:
    def __init__(self, cache_path: str | Path = "data/geocode_cache.json"):
        self.cache_path = Path(cache_path)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, list[float] | None] = {}
        if self.cache_path.exists():
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except json.JSONDecodeError:
                self._cache = {}
        self._last_nominatim = 0.0
        self._dirty = 0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT

    # Write the cache to disk at most once every this many new lookups.
    # A crash loses only the trailing few entries (each ~1 s to recompute),
    # in exchange for not rewriting the whole file on every single lookup.
    _SAVE_EVERY = 25

    def _save(self) -> None:
        self.cache_path.write_text(json.dumps(self._cache, indent=0))

    def _mark_dirty(self) -> None:
        self._dirty += 1
        if self._dirty >= self._SAVE_EVERY:
            self.flush()

    def flush(self) -> None:
        """Persist any buffered cache entries.  Call when a batch finishes."""
        if self._dirty:
            self._save()
            self._dirty = 0

    def _cached(self, key: str):
        return self._cache.get(key)

    # -- providers ----------------------------------------------------
    def _zip_lookup(self, zip_code: str) -> tuple[float, float] | None:
        key = f"zip:{zip_code}"
        if key in self._cache:
            v = self._cache[key]
            return tuple(v) if v else None
        try:
            resp = self.session.get(
                f"https://api.zippopotam.us/us/{zip_code}", timeout=15
            )
            if resp.status_code == 200:
                place = resp.json()["places"][0]
                coords = (float(place["latitude"]), float(place["longitude"]))
                self._cache[key] = list(coords)
                self._mark_dirty()
                return coords
            self._cache[key] = None
            self._mark_dirty()
        except (requests.RequestException, KeyError, ValueError, IndexError):
            log.debug("zip lookup failed for %s", zip_code)
        return None

    def _nominatim_lookup(self, city: str, state: str) -> tuple[float, float] | None:
        key = f"city:{city.lower()},{state.lower()}"
        if key in self._cache:
            v = self._cache[key]
            return tuple(v) if v else None
        wait = 1.1 - (time.time() - self._last_nominatim)
        if wait > 0:
            time.sleep(wait)
        try:
            resp = self.session.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "city": city, "state": state, "country": "USA",
                    "format": "json", "limit": 1,
                },
                timeout=20,
            )
            self._last_nominatim = time.time()
            if resp.status_code == 200 and resp.json():
                hit = resp.json()[0]
                coords = (float(hit["lat"]), float(hit["lon"]))
                self._cache[key] = list(coords)
                self._mark_dirty()
                return coords
            self._cache[key] = None
            self._mark_dirty()
        except (requests.RequestException, KeyError, ValueError, IndexError):
            log.debug("nominatim lookup failed for %s, %s", city, state)
        return None

    # -- public -------------------------------------------------------
    def locate(self, city: str, state: str, address: str = "") -> tuple[float, float, bool]:
        """Return (lat, lon, approximate).

        ``approximate`` is True when only the state centroid was found.
        """
        m = ZIP_RE.search(address or "")
        if m:
            coords = self._zip_lookup(m.group(1))
            if coords:
                return coords[0], coords[1], False
        if city and state:
            coords = self._nominatim_lookup(city, state)
            if coords:
                return coords[0], coords[1], False
        centroid = STATE_CENTROIDS.get(state.upper())
        if centroid:
            return centroid[0], centroid[1], True
        # Unknown state: pretend it's at home so it's neither included nor
        # crashed on; caller filters on drive time anyway.
        return config.HOME_LAT, config.HOME_LON, True


def drive_estimate(lat: float, lon: float) -> tuple[float, float]:
    """Estimated (road_miles, drive_hours) one-way from home base."""
    straight = haversine_miles(config.HOME_LAT, config.HOME_LON, lat, lon)
    road_miles = straight * config.ROAD_CIRCUITY
    return road_miles, road_miles / config.AVG_MPH
