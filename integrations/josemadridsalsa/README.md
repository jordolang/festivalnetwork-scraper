# josemadridsalsa.com integration

TypeScript for the **"Find my next 3 months of shows"** button on the admin
panel.

| File | What it does |
|------|--------------|
| `runExport.ts` | Spawns the scraper, waits for it, returns the parsed plan |
| `festivalImport.ts` | CSV reader + `Show` type + the column contract |

Both are server-side only — `runExport` shells out to Python.

## Using it

```ts
import { runExport } from '@/integrations/josemadridsalsa/runExport'

const result = await runExport({
  projectDir: process.env.FNSCRAPER_DIR!,   // checkout of this repo
  months: 3,
  top: 5,
  onProgress: (line) => logger.info(line),  // live status for the UI
})

// result.rows is Show[], already typed and parsed
await db.shows.upsertMany(result.rows)      // natural key: row.url
```

A cold run crawls ~2,000 listings and takes tens of minutes, so run it from
a job/queue rather than inside a request. Pass `cached: true` for a
"regenerate from the last scrape" button that returns in about a second.

### Importing a CSV the user uploads instead

```ts
import { parseShowCsv } from '@/integrations/josemadridsalsa/festivalImport'

const shows = parseShowCsv(await file.text())
```

`parseShowCsv` throws `ShowImportError` when the header doesn't match the
expected 20 columns exactly — better a loud failure than a silent column
shift after a format change.

## The CSV format

One row per show. **UTF-8 with BOM**, `\r\n` line endings, RFC-4180 quoting
(only fields containing a comma, quote, or newline get quoted). A copy of
this spec is written next to every export as `SPEC.md`.

```
Event Name,Venue,Address,City,ST,Drive-Time,Start Date,End Date,Times,Application Deadline,Booth Fee,Attendance,# of Exhibitors,Cost of Fuel,Lodging,Meals,Contact Name,Contact Email Address,Application Information,URL of Festivalnet posting
```

| # | Column | Type | Notes |
|---|--------|------|-------|
| 1 | Event Name | text | As listed on FestivalNet |
| 2 | Venue | text | May be empty |
| 3 | Address | text | Full mailing line: `street, city, ST ZIP` |
| 4 | City | text | |
| 5 | ST | text | Two-letter state code |
| 6 | Drive-Time | `Hh MMm` | One way from Zanesville, OH. `3h 42m` |
| 7 | Start Date | `MM/DD/YYYY` | |
| 8 | End Date | `MM/DD/YYYY` | Equals Start Date for one-day shows |
| 9 | Times | text | `Sat 10am-6pm; Sun 11am-5pm` |
| 10 | Application Deadline | `MM/DD/YYYY` or text | Can hold `until full` / `Not listed` |
| 11 | Booth Fee | `$0.00` | |
| 12 | Attendance | integer | |
| 13 | # of Exhibitors | integer | |
| 14 | Cost of Fuel | `$0.00` | Round trip, 20 mpg |
| 15 | Lodging | `$0.00` | `$0.00` means a day trip |
| 16 | Meals | `$0.00` | Per diem for the trip |
| 17 | Contact Name | text | Director, falling back to the promoter org |
| 18 | Contact Email Address | email | Empty when not published |
| 19 | Application Information | text | How to get the form, plus the website |
| 20 | URL of Festivalnet posting | url | **Natural key** — upsert on this |

### Two rules that will bite you

**A trailing `*` means "estimated".** It can appear on Booth Fee,
Attendance, and `# of Exhibitors`. It means FestivalNet did not publish the
value and the scraper substituted a model default. Strip it before parsing
a number, and surface it in the UI — those rows need confirming with the
promoter before you commit to the show.

```
$150.00*            estimated booth fee
$150.00* (Contact)  estimated, and the listing says to ask the promoter
$125.00             the promoter's real published fee
```

**An empty cell means "not published", never zero.** Only `Lodging` uses a
real `$0.00` to mean zero (a day trip). Everywhere else, blank is unknown —
don't coerce it to `0` or the profitability maths downstream will lie.
