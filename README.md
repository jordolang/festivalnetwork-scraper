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

When the scrape finishes (in a real terminal) an **interactive picker**
opens: a scrolling checkbox list of every qualifying show, sorted by
**state, then date, then cost**. Each row shows the estimated
**out-of-pocket cost to sell one jar of salsa** (`$/JAR`), the total cost
of doing the show, drive time, location, date, and name:

```
    ST  DATE             $/JAR     SHOW $   DRIVE  EVENT
[x] OH  Jul 10-11        $1.96       $734    1.8h  Summit County Italian American Festival — Akron
[ ] OH  Jul 11-12        $1.79       $499    2.3h  Youngstown Summer Festival of the Arts — Youngstown
```

Keys: **SPACE** checks/unchecks the show next to the cursor (arrow keys /
PgUp / PgDn scroll), **ENTER** saves your picks and exits, `q` quits
without saving. Reopen the same list later without re-scraping:

```bash
python -m fnscraper --browse
```

When you save, your checked shows are exported with **every data field**
(50 columns — identity, dates, location, attendance, exhibitors, fees,
all cost components, profit estimates, notes) to:

- `reports/selected_shows.xlsx` — spreadsheet (bold header, freeze pane, filters, currency formatting)
- `reports/selected_shows.csv`
- `reports/selected_shows.md` — markdown table
- `reports/shortlist.md` — a readable per-show summary with apply deadlines and links

Every full run also writes:

- `reports/weekend_picks.md` — top picks for each upcoming weekend
- `reports/all_events.csv` — every scored event, all fields
- `reports/results.json` — saved results that power `--browse`

Useful flags:

```bash
python -m fnscraper --weeks 12 --top 8          # longer horizon, more picks
python -m fnscraper --states Ohio Pennsylvania  # limit the crawl
python -m fnscraper --max-drive-hours 6         # tighter radius
python -m fnscraper --refresh                   # ignore the page cache
python -m fnscraper --no-pick                   # skip the picker, print the list
python -m fnscraper --browse                    # reopen picker on last results
python -m fnscraper --deadline-by 2026-08-01    # applications due by this date
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

## Applying to shows: import + application autofill

Once you've exported a selection, hand it back to the tool and it will go
get the applications:

```bash
python -m fnscraper apply                          # uses reports/selected_shows.csv
python -m fnscraper apply reports/selected_shows.xlsx
python -m fnscraper apply my_picks.md --limit 3
```

Any of the three export formats imports losslessly. For each show it:

1. **Re-locates the listing** on FestivalNet and extracts the promoter's
   website (decoding FestivalNet's redirect slugs). If the public listing
   hides the website, it falls back to a web search and only accepts a
   site after verifying the event is actually named on it
   (`--no-search` disables this).
2. **Hunts for applications** — crawls the promoter site shallowly,
   scoring links for vendor/exhibitor application language (and
   penalizing permits, sponsorships, volunteer forms), downloading
   matching PDFs/DOCs and recording online forms (Jotform, Google Forms,
   Zapplication, Eventeny, …).
3. **Auto-fills fillable PDFs** from your `vendor_profile.json` (copy
   `vendor_profile.example.json`, fill in your business info) using fuzzy
   field matching — "Business Name", "Company", "biz_name" all map
   correctly. Flat/scanned PDFs and online forms get an `ANSWERS.md`
   copy-paste sheet instead.

Everything lands in the repo under `applications/`:

```
applications/
  INDEX.md                                  # status of every show
  manifest.json
  2026-07-10_OH_Walkabout-Tremont-July/
    README.md                               # dates, deadlines, links, notes
    downloads/VendorApplication.pdf         # as downloaded
    VendorApplication__FILLED.pdf           # auto-filled — REVIEW FIRST
    ANSWERS.md                              # copy-paste sheet for web forms
```

`applications/` and `vendor_profile.json` are gitignored by default since
they contain your personal contact info — delete those lines from
`.gitignore` if you want them committed.

**Always review an auto-filled application before sending it.** Promoters
notice sloppy applications, and no field-matcher is perfect.

## Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Parser tests run against synthetic fixtures that mirror FestivalNet's
schema.org markup; scoring tests pin the model's behavior (long drives add
hotels, crowded shows rank lower, real fees override estimates, etc.).
