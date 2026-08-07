# festivalnetwork-scraper

Finds the **most profitable shows for the lowest out-of-pocket cost** for a
vendor working expos, fairs, festivals, and craft shows — scanning every
upcoming weekend within driving distance of home.

Set up once with your own home town, prices, costs, and travel limit, and
it ranks every event it can find by what it should actually put in your
pocket. It was built for a salsa vendor in Zanesville, Ohio, and those are
still the built-in defaults, but nothing about it is specific to salsa or
to Ohio — **[install it on a Windows PC](#install-it-on-a-windows-pc)** and
it asks you for your own numbers.

> **Note on the site:** `festivalnetwork.com` is a dead domain. The event
> database this project scrapes is **[festivalnet.com](https://festivalnet.com)**
> (FestivalNet), which lists 26,000+ North American events with public
> attendance, exhibitor, admission, and location data.

---

# Install it on a Windows PC

**Everything below is for someone who has never opened a command prompt.
There is nothing to install first, nothing to type, and nothing to
configure by hand.**

## 1. Download it

**[Click here to download it](https://github.com/jordolang/festivalnetwork-scraper/archive/refs/heads/main.zip)**
— it lands in your **Downloads** folder as
`festivalnetwork-scraper-main.zip`.

> The green **Code → Download ZIP** button on the repository page gets
> you the same thing — the link above just skips a step.

## 2. Unzip it

Find `festivalnetwork-scraper-main.zip` in Downloads. **Right-click it →
Extract All… → Extract.**

> **This step matters.** If you double-click the installer while it is
> still inside the ZIP, Windows only unpacks that one file and the
> install will stop and tell you so. Extract first.

## 3. Double-click **Install**

Open the folder that appeared and double-click the file called
**Install** (Windows may show it as `Install.cmd`).

A blue box saying **"Windows protected your PC"** may appear. That is
Windows being cautious about any file downloaded from the internet, not a
sign of a problem. Click **More info**, then **Run anyway**.

A black window opens and does the rest by itself:

| Step | What happens | How long |
|------|--------------|----------|
| 1 | Checks the download is complete | instant |
| 2 | Finds Python — **and installs it for you if the PC doesn't have it** | 0–2 min |
| 3 | Copies the program to a permanent folder so it keeps working after you empty Downloads | seconds |
| 4 | Builds its own private Python environment and downloads the libraries it needs | 1–2 min |
| 5 | Puts three icons on your Desktop and in the Start Menu | seconds |
| 6 | Asks you the questions below, so it plans shows using **your** prices | 3–5 min |

No administrator password is needed, nothing else on the PC is changed,
and no existing Python is modified.

## 4. Answer the questions

The last part of the install is a setup wizard. Every question shows a
suggested answer in `[brackets]` — press **Enter** to accept it. Rough
estimates are fine; you can change any of it later.

| It asks | What it's for | Example |
|---------|---------------|---------|
| **Your business name** | Labels your reports and gives them their own folder | `Jose Madrid Salsa` |
| **City, state, ZIP** | Every distance, fuel cost, and hotel decision is measured from here | `Zanesville`, `OH`, `43701` |
| **Longest one-way drive** | Shows farther than this are ignored completely | `10` hours |
| **Which states to search** | It works this out from your location and drive limit and shows you the list — press Enter to accept | 20 states |
| **What you call one item** | Used on reports (`$/JAR`, `$/CANDLE`) | `jar` |
| **Price of one item** | Your normal retail price | `10` |
| **What it costs you to make one** | Ingredients + packaging for one item, not a percentage | `3.50` |
| **Your usual multi-item deal** | Most customers buy a package, not one item — this is the single biggest driver of the estimate | `3` for `$25` |
| **A cheap add-on** *(optional)* | Chips, a drink, a sample bag — and how many customers in 100 also buy one | `$3` chips, `12` in 100 |
| **Miles per gallon** | Your loaded van or truck, not the sticker figure | `20` |
| **Gas price** | Per gallon | `4.00` |
| **Hotel per night** | Only charged when the drive is over 2½ hours | `150` |
| **Food per day** | On the road | `35` |
| **When a hotel is needed** | The longest drive you'll do there-and-back in one day. Anything longer adds a hotel night to that show's cost | `2.5` hours |
| **How many months ahead to plan** | Promoters take applications well in advance, so this is usually longer than you'd think | `6` months |
| **Shows per weekend** | How many options you want to choose between for each weekend | `10` |
| **FestivalNet Pro login** *(optional)* | With one, it reads **real booth fees, application deadlines, and promoter emails** instead of estimating them. This is worth more than every other setting combined — see [Booth fees, deadlines, and promoter contacts](#booth-fees-deadlines-and-promoter-contacts) | your login |
| **Your application details** | Name, address, phone, email, tax ID, booth size, insurance — these get typed into vendor applications for you | — |

Nothing is saved until you confirm at the end, and the wizard shows you a
summary first. **You never edit a configuration file** — every number the
tool uses comes from these answers, and the same wizard reopens from the
**Settings** icon whenever anything changes.

## 5. Use it

Three icons are now on the Desktop:

| Icon | What it does |
|------|--------------|
| **Show Finder – Find My Shows** | Searches for the most profitable shows to book and opens the folder with the results |
| **Show Finder – Pick Shows** | Opens the list of shows so you can tick the ones you want, then saves them to a spreadsheet |
| **Show Finder – Settings** | Re-runs the questions above to change prices, costs, or how far you'll drive |

Two more live in the Start Menu under **Show Finder**: *Get The
Applications* (downloads and fills in vendor applications for the shows
you ticked) and *Open My Results*.

**The first search takes 45–75 minutes.** It reads a few thousand event
listings and is deliberately slow so it doesn't hammer FestivalNet's
site. Leave the window open — it prints what it's doing as it goes, and
you can keep using the PC for other things. After that first run,
re-planning takes seconds.

## Changing your settings later

Double-click **Show Finder – Settings**. It fills in everything you
answered before, so you only change what you want and press Enter through
the rest.

Your answers live in a plain text file called `business.json` inside the
install folder. Anyone comfortable editing text can open it directly —
the wizard is just a friendlier way to write it:

| In `business.json` | Means |
|--------------------|-------|
| `business_name` | Names your report folder (`reports/<your-business>/`) |
| `home` | City, state, ZIP and map coordinates you start from |
| `max_drive_hours` | One-way drive limit |
| `states` | Which state listings get searched |
| `product.unit_price` / `unit_cost` | What one item sells for / costs you to make |
| `product.deal_units` / `deal_price` | Your usual package deal |
| `product.addon_*` | The cheap add-on and how often it sells |
| `travel.*` | mpg, gas price, hotel, food |
| `planning.months_ahead` / `top_per_weekend` | How far ahead to plan and how many shows per weekend |
| `advanced` | Any constant from [`fnscraper/config.py`](fnscraper/config.py), by its exact name — for tuning the model itself |

Delete `business.json` and the program falls back to the built-in
defaults. A bad edit is reported and ignored rather than crashing.

## Setting it up for a different business

Nothing in the download is specific to one business — the defaults are
just the ones this project was first tuned on, and the setup wizard
replaces every one of them. Install it on the new PC exactly as above and
answer the questions with that business's own numbers.

## Where it goes, and removing it

Installed to `%LOCALAPPDATA%\Programs\ShowFinder` (per-user, no admin
rights). Results, settings, and downloaded applications all live inside
that folder. To remove it, open the Start Menu folder **Show Finder** →
`Uninstall`, or run `Uninstall.bat` from the install folder.

## If something goes wrong

| What you see | What to do |
|--------------|------------|
| "Windows protected your PC" | Click **More info → Run anyway**. It appears for any downloaded file that isn't code-signed. |
| "The program files are not all here" | The installer was run from inside the ZIP. Extract the ZIP first, then run Install from the extracted folder. |
| "Python could not be downloaded" | The PC is offline or a company firewall is blocking it. Reconnect and run Install again, or install Python yourself from [python.org](https://www.python.org/downloads/) (tick **Add python.exe to PATH**) and re-run Install. |
| "The libraries could not be installed" | Same cause — the connection or a firewall blocking `pypi.org`. Run Install again; nothing has to be undone first. |
| A window flashes and vanishes | Run **Install** again and read the message before it closes; the full log is at `%TEMP%\ShowFinder-install.log`. |
| The search ends with no shows | Your drive limit is probably too tight, or every deadline in range has passed. Open **Settings** and raise the drive time. |
| The list of shows won't open | The picker needs the `windows-curses` package, which the installer adds automatically. Everything else — searching, reports, the CSV — works without it, and the list prints as plain text instead. Re-run **Install** to add it. |
| The list is cut off at the right | Maximise the window, or drag it wider. The launcher asks for a 150-column window; some terminals ignore that. |
| Antivirus blocks the installer | It is a plain text script — you or your IT can read `Install.cmd` and `windows\install.ps1` in Notepad before allowing it. |

Whatever happens, `%TEMP%\ShowFinder-install.log` records every step and
is safe to send to whoever set this up for you. It contains no passwords.

## If you are the one distributing this

**Send people the GitHub ZIP link or a Release, never a ZIP you made of
your own folder.** Your working copy contains `.env` (your FestivalNet
password), `vendor_profile.json` (your address and tax ID), and
`business.json` (your costs). Those three are excluded from git, so a
GitHub download is clean — a hand-made ZIP of your folder would mail
another business your credentials.

---

## Quick start (Mac, Linux, or from a terminal)

```bash
pip install -r requirements.txt
python -m fnscraper setup      # configure it for your business
python -m fnscraper best
```

That last command is the whole job: it finds the best shows to book for
every weekend of the next three months and writes them to a CSV. Read on
for what it does and how to tune it.

## The one-button booking plan

`fnscraper best` answers the standing question — *"what should I book for
the next three months?"* — in a single command. For **every weekend** in
the window it picks the five most profitable shows that are still open for
applications, and writes them as a CSV the Jose Madrid Salsa admin panel
imports directly.

### Running it

```bash
cd /path/to/festivalnetwork-scraper
python -m fnscraper best
```

**A cold run takes 45–75 minutes.** It crawls ~2,000 listings across 20
states, geocodes every distinct city (rate-limited to ~1/sec by
OpenStreetMap), then fetches a detail page per event. Progress prints as it
goes. Leave it running.

Once it has run once, re-planning is instant:

```bash
python -m fnscraper best --cached        # ~1 second, no network
```

`--cached` re-scores the last crawl from `reports/results.json`. Use it
whenever you change a price, a cost, or a setting in `config.py` — the
rankings update immediately without re-crawling. Re-crawl only when you
want *newer listings*, which is worth doing every week or two.

### Options

```bash
python -m fnscraper best --months 6              # plan further ahead
python -m fnscraper best --top 8                 # 8 shows a weekend instead of 5
python -m fnscraper best --max-drive-hours 5     # tighter radius
python -m fnscraper best --states Ohio Kentucky  # only these states
python -m fnscraper best --max-repeats 1         # a recurring market gets one weekend
python -m fnscraper best --include-fairs          # fairs are excluded by default
python -m fnscraper best --categories crafts food # only these kinds of show
python -m fnscraper best --refresh               # ignore the page cache, re-fetch all
python -m fnscraper best --json                  # machine-readable summary on stdout
python -m fnscraper best -j 8                    # more parallel fetches (faster, less polite)
```

`--json` prints only a JSON object on stdout (progress goes to stderr), so
a script or a website button can read the result. That is what the admin
panel integration uses.

### What you get

Output lands in a dated directory so exports never collide:

```
reports/josemadridsalsa/export072426-101826/
├── export072426-101826.csv     <- import this
├── IMPORT_FORMAT.md            <- the full importer contract
└── SPEC.md                     <- a short column reference
```

The stamps are the first and last **show date** the plan books, `MMDDYY`.
A typical 3-month plan is **65 shows across 13 weekends**.

`IMPORT_FORMAT.md` is the document to hand to whoever builds or maintains
the import — it specifies the encoding, every field, the validation rules,
and a suggested database schema. It is copied into every export so the
spec can never drift from the data.

### Before your first run

Run `python -m fnscraper setup` once. It asks for your home base, prices,
costs, travel limits, and FestivalNet login, and writes them to
`business.json`, `.env`, and `vendor_profile.json` — the same wizard the
Windows installer runs. (Windows users never need to do this by hand; see
[Install it on a Windows PC](#install-it-on-a-windows-pc).)

Credentials can also be placed in a `.env` file at the project root by
hand:

```
FESTIVALNET_USER=your-username
FESTIVALNET_PASS=your-password
```

This matters more than anything else you can configure. Logged in, the
scraper gets **real booth fees, application deadlines, and promoter email
addresses** (≈97% coverage). Without it those are estimates or missing
entirely. See [Booth fees, deadlines, and promoter contacts](#booth-fees-deadlines-and-promoter-contacts).

A show earns a slot only if it actually runs on a bookable day — **Wed
through Sun**, with Fri/Sat/Sun preferred. A show that only runs Mon/Tue is
dropped outright; one that misses the prime days is ranked as if it were
worth 30% less, so it wins a slot only when nothing better is on that
weekend. Shows whose application deadline has already passed are dropped,
and one recurring market can hold at most two weekends (`--max-repeats`) so
a weekly flea market can't quietly fill the whole quarter.

Weekly series are read honestly: a listing that spans `07/23–07/30` but
whose hours say *"Thursdays 5pm–9pm"* is treated as open on Thursdays only,
not straight through both weekends.

### Wiring it to a button on josemadridsalsa.com

[`integrations/josemadridsalsa/`](integrations/josemadridsalsa/) has
everything the website needs:

| File | Purpose |
|------|---------|
| `AGENT_INTEGRATION_BRIEF.md` | Hand this to an AI coding agent to build the admin-panel button |
| `IMPORT_FORMAT.md` | The CSV contract — encoding, every field, validation rules, schema |
| `runExport.ts` | `runExport()` spawns the scraper and returns typed rows |
| `festivalImport.ts` | `parseShowCsv()` — CSV → typed `Show[]`, strict header check |

```ts
const result = await runExport({ projectDir: '/srv/festivalnetwork-scraper' })
await db.shows.upsertMany(result.rows)   // natural key: row.url
```

A cold run takes 45–75 minutes, so drive it from a background job rather
than a request handler; `cached: true` re-plans in about a second and is
the right thing behind a "refresh rankings" button.

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
PgUp / PgDn scroll), `c` opens a **category filter** (check/uncheck Arts,
Crafts, Festivals, Expos, …), `o` toggles date/deadline ordering, `d` shows
the full detail popup, **ENTER** saves your picks and exits, `q` quits
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
python -m fnscraper --jobs 8                     # fetch faster (more parallel requests)
python -m fnscraper --jobs 1                     # slowest, most polite crawl
python -m fnscraper --refresh                   # ignore the page cache
python -m fnscraper --no-pick                   # skip the picker, print the list
python -m fnscraper --browse                    # instant: reopen last results, no network
python -m fnscraper --deadline-by 2026-08-01    # applications due by this date
python -m fnscraper --categories arts crafts festival home-garden  # just these kinds
python -m fnscraper --include-fairs             # add fairs back in
python -m fnscraper --all-categories            # everything, fairs included
python -m fnscraper --list-categories           # print the category keys
```

### Loading results quickly

Two things make repeat use fast:

- **`--browse`** replays the *last* scrape's results from `reports/results.json`
  instantly, with zero network calls. Use it whenever you just want to re-open
  the picker or re-export — no reason to re-crawl.
- **`--jobs N`** controls how many FestivalNet pages are fetched in parallel on a
  fresh scrape (default `4`). The crawl's aggregate request rate stays polite
  (`~N / 1.5` requests/sec), so a higher `N` finishes a cold run proportionally
  faster; `--jobs 1` restores the original strictly-sequential crawl. Geocoding
  stays sequential regardless, to respect the OpenStreetMap ~1 req/sec policy.

Pages are also cached on disk for ~20 hours, so even without `--browse` a second
run within the day mostly reuses the cache and skips the network entirely.

## Categories: no fairs by default

The vendor here works packaged salsa, so the target is **arts & crafts
festivals and expos** — not carnival-and-rides county/state fairs. By
default the crawl **skips fairs entirely** (they're dropped before any
geocoding or detail-fetch, so they never cost a request), keeping every
other category.

Pick exactly what you want in two places:

- **Command line** — `--categories arts crafts festival home-garden` limits
  the scrape; `--include-fairs` adds fairs back; `--all-categories` keeps
  everything; `--list-categories` prints the keys (`arts`, `crafts`,
  `food`, `farmers-market`, `music`, `holiday`, `home-garden`, `fair`,
  `festival`, `other`).
- **In the picker** — press `c` for a checkbox list of the categories in
  your results and toggle them on/off live. Selections you've already
  checked are kept even if you later hide their category, so filtering the
  view never drops a show from your export.

`fnscraper best` takes the same four flags and applies them identically
whether it crawls fresh or replays a cache with `--cached`, so the booking
plan can never disagree with itself about what counts as a show worth
booking.

Categories are derived from FestivalNet's own URL slugs (`/Art-Shows/`,
`/Craft-Shows/`, `/Fairs/`, …); the slug→category mapping lives in
[`fnscraper/categories.py`](fnscraper/categories.py) if you want to tune it.

One consequence worth knowing: the crawl drops unselected categories
*before* saving `reports/results.json`, so `--include-fairs` on a later
`--cached` run can only surface fairs that were in range when the crawl
ran. Re-crawl with `--all-categories` if you want everything on disk.

## The algorithm

Every event inside the date window and drive radius gets scored:

```
buyers        = attendance / 40                  (1 sale per 40 visitors)
                x category fit                   (food fest 1.20 ... home show 0.80)
                x competition factor             (sqrt of attendees-per-booth vs ideal 150)
                x admission factor               (free-entry crowds buy more)
                x data-quality factor            (unconfirmed/stale listings docked)

buyers        = max(buyers, attendance / 40)             ("...or better" floor)
buyers        = min(buyers, 150 sales/day x show days)   (one booth's physical limit)
revenue       = buyers x $25 average order               (the 3-for-$25 deal)
jars sold     = buyers x 3 jars per order                (NOT revenue / $10)
cost of goods = jars sold x $3.50 to produce a jar
out of pocket = booth fee + fuel (round trip, 20 mpg) 
                + hotel ($110/night when the drive > 2.5 h)
                + meals ($35/day)
profit        = revenue - cost of goods - out of pocket

SCORE = profit x sqrt(profit / out-of-pocket)
```

**Sales assumptions.** Customers buy *packages*, not jars, so the model is
priced per order off the real deal ladder:

| Deal | Price | $/jar | COGS | Margin |
|------|-------|-------|------|--------|
| 1 jar | $10 | $10.00 | $3.50 | 65% |
| 3 jars | $25 | $8.33 | $10.50 | 58% |
| 4 jars | $32 | $8.00 | $14.00 | 56% |
| 5 jars + chips | $40 | $8.00 | $18.50 | 54% |
| case of 12 | $80 | $6.67 | $42.00 | 48% |
| bag of chips | $3 | — | $1.00 | **67%** |

The **$25 average order is the 3-for-$25 deal, so it moves three jars** —
dividing revenue by the $10 single-jar price would call it 2.5 and
understate the salsa consumed by 20%. `ORDER_MIX` in
[`config.py`](fnscraper/config.py) sets how the day's orders split across
the ladder; it defaults to all-$25-deals and `avg_sale()`,
`jars_per_order()` and `cogs_per_order()` are all derived from it, so they
can never drift apart. Drop in real till data when you have it.

**Chips are the best margin at the booth** — 67% on a $3 bag over a $1
cost, better than any salsa deal. About **1 order in 8** adds a bag
(`CHIPS_ATTACH_RATE = 0.125`), worth $25 of margin per hundred orders.
That figure is the vendor's own read rather than till data, so it is the
softest number in the model; each point of attach rate moves margin by
$2.00 per hundred orders. Note also that the 5-for-$40 deal charges five
jars at the 4-jar rate and throws the bag in — it costs $1.00 and forgoes
$3.00 of chip sales.

Conversion is **1 sale per 40 people through the gate, or better** — the multipliers above can push the
estimate up from that baseline but never below it, so no show is modelled as
converting worse than 1-in-40.

**Cost of goods** is **$3.50 a jar**, not a percentage of revenue. A batch
runs ~$1,500 of ingredients plus ~$1,000 of jars and lids, and the true unit
cost sits between $2.50 and $3.50; the model takes the top of that band,
because overstating cost is the safe direction when deciding whether a show
pays. Pricing it per jar also means COGS stays put when the shelf price
moves — under a percentage, raising the jar to $12 would silently invent 20%
more ingredient cost.

Once you know how many jars a batch actually fills, set `BATCH_JARS` in
[`config.py`](fnscraper/config.py) and the per-jar cost is derived from your
real batch economics ($2,500 / 715 jars = $3.50; $2,500 / 1,000 = $2.50).

That final score is the "most profit for the least cash risked" ranking:
two events with the same estimated profit are ordered by which one risks
less money, and money-losing events go negative and sink. Events are then
grouped by weekend (Fri–Sun; Sunday joins the preceding Saturday) and the
top N per weekend are reported.

Every constant — gas price, mpg, average sale, capture rate, fee tiers,
category weights — lives in [`fnscraper/config.py`](fnscraper/config.py) so
you can tune the model as your real sales numbers come in. Those are the
*defaults*; anything in `business.json` overrides them at startup, so per
business tuning never means editing Python. Raw constants can be set there
too, under `advanced`:

```json
{ "advanced": { "CAPTURE_RATE": 0.012, "MAX_DAILY_TRANSACTIONS": 200 } }
```

### Booth fees, deadlines, and promoter contacts

FestivalNet hides the details that actually matter behind its Pro
membership. Anonymously, fees are **estimated from attendance tiers** ($75
for tiny shows up to $750 for mega-festivals, x1.4 when the event hosts
food booths) and flagged with `~` in reports (`*` in the booking-plan CSV).

With a Pro account in `.env` (or the environment):

```bash
export FESTIVALNET_USER=you
export FESTIVALNET_PASS=secret
```

the scraper logs in and picks up the **real booth fee, the per-track
application deadlines, how and where to apply, the show/exhibit director's
name, phone, and email, and the promoter's website**.

Logged-in pages are a *completely different document* from the public ones
— a legacy `<font class="font-color">Label:</font>` table instead of the
public microdata + `<li>` list — with email addresses obfuscated behind
`eval(unescape('%hex'))`. `parse.py` sniffs which layout it received and
dispatches accordingly, so a Pro session and an anonymous one both parse
correctly. Without that dispatch a logged-in run silently yields *less*
data than an anonymous one.

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
3. **Auto-fills fillable PDFs** from your `vendor_profile.json` (written
   by `python -m fnscraper setup`; `vendor_profile.example.json` shows the
   fields) using fuzzy field matching — "Business Name", "Company", "biz_name" all map
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
