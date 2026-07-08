# festivalnetwork-scraper

Finds the **most profitable shows for the lowest out-of-pocket cost** for a
salsa vendor working expos, fairs, festivals, and craft shows — scanning
every upcoming weekend within a **10-hour drive of Zanesville, Ohio**.

> **Note on the site:** `festivalnetwork.com` is a dead domain. The event
> database this project scrapes is **[festivalnet.com](https://festivalnet.com)**
> (FestivalNet), which lists 26,000+ North American events with public
> attendance, exhibitor, admission, and location data.

## Quick start

```bash
pip install -r requirements.txt
python -m fnscraper --weeks 8
```

Outputs:

- `reports/weekend_picks.md` — top picks for each upcoming weekend
- `reports/all_events.csv` — every scored event with the full cost/revenue breakdown
- A console summary of the best pick per weekend

Useful flags:

```bash
python -m fnscraper --weeks 12 --top 8          # longer horizon, more picks
python -m fnscraper --states Ohio Pennsylvania  # limit the crawl
python -m fnscraper --max-drive-hours 6         # tighter radius
python -m fnscraper --refresh                   # ignore the page cache
```

## The algorithm

Every event inside the date window and drive radius gets scored:

```
buyers        = 0.045 x attendance^0.88          (capture shrinks at mega-events)
                x category fit                   (food fest 1.20 ... home show 0.80)
                x competition factor             (sqrt of attendees-per-booth vs ideal 150)
                x admission factor               (free-entry crowds buy more)
                x data-quality factor            (unconfirmed/stale listings docked)

buyers        = min(buyers, 150 sales/day x show days)   (one booth's physical limit)
revenue       = buyers x $10 average sale
out of pocket = booth fee + fuel (round trip, 20 mpg) 
                + hotel ($110/night when the drive > 2.5 h)
                + meals ($35/day)
profit        = revenue - 35% cost of goods - out of pocket

SCORE = profit x sqrt(profit / out-of-pocket)
```

That final score is the "most profit for the least cash risked" ranking:
two events with the same estimated profit are ordered by which one risks
less money, and money-losing events go negative and sink. Events are then
grouped by weekend (Fri–Sun; Sunday joins the preceding Saturday) and the
top N per weekend are reported.

Every constant — gas price, mpg, average sale, capture rate, fee tiers,
category weights — lives in [`fnscraper/config.py`](fnscraper/config.py) so
you can tune the model as your real sales numbers come in.

### Booth fees

FestivalNet hides exact booth fees behind its Pro membership, so by default
fees are **estimated from attendance tiers** ($75 for tiny shows up to $750
for mega-festivals, x1.4 when the event hosts food booths) and flagged with
`~` in reports. If you have a Pro account, export:

```bash
export FESTIVALNET_USER=you
export FESTIVALNET_PASS=secret
```

and the scraper logs in and uses the **real Exhib./Food fees** wherever the
site shows them.

### Distance filtering

Events are geocoded (street-address ZIP via zippopotam.us, city via
OpenStreetMap Nominatim, cached in `data/geocode_cache.json`), converted to
road miles with a 1.25 circuity factor, and to drive time at 58 mph. Only
events within the one-way limit (default 10 h) survive. The crawl covers all
20 states that can fall inside that radius.

## How it crawls

1. Walks `/fairs-festivals/<State>?page=N` for each state — pages are
   date-sorted, so crawling stops at the horizon instead of paging through
   thousands of events.
2. Pre-filters by city distance, then fetches detail pages only for events
   in range, pulling attendance, exhibitor count, admission, street
   address, hours, juried status, deadlines, and promoter.
3. Scores, ranks, groups by weekend, writes reports.

The scraper is polite by design: a descriptive User-Agent, 1.5 s between
requests, retries with backoff, and a 20-hour on-disk page cache so re-runs
don't touch the site. `robots.txt` permits this crawl (only `/stats/` and
`/clicktrack/` are disallowed); keep usage personal and respect
FestivalNet's terms — the data stays on your machine for your own show
planning.

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Parser tests run against synthetic fixtures that mirror FestivalNet's
schema.org markup; scoring tests pin the model's behavior (long drives add
hotels, crowded shows rank lower, real fees override estimates, etc.).
