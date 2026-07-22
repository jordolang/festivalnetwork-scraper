# Brief: add a "Find Shows" button to the Jose Madrid Salsa admin panel

You are integrating an existing Python tool into the josemadridsalsa.com
admin panel. **The scraper is finished and tested — do not modify it.**
Your job is the web layer: a button that runs it, stores the results, and
shows them.

---

## 1. What already exists

A Python CLI at `festivalnetwork-scraper/` that finds the most profitable
festivals for a salsa vendor to book, weekend by weekend.

```bash
cd /path/to/festivalnetwork-scraper
python -m fnscraper best --json
```

It writes a CSV and prints a JSON summary on **stdout**. Progress and
warnings go to **stderr**, so stdout is safe to parse.

```json
{
  "csv": "reports/josemadridsalsa/export072426-101826/export072426-101826.csv",
  "spec": "reports/josemadridsalsa/export072426-101826/SPEC.md",
  "shows": 65,
  "weekends": 13,
  "first_weekend": "2026-07-25",
  "last_weekend": "2026-10-17",
  "columns": ["Event Name", "Venue", "..."]
}
```

The `csv` path is **relative to the scraper's working directory**. Resolve
it against `projectDir` before opening it.

Exit code `0` means success. Non-zero means failure, and the last few lines
of stderr explain why.

### Two modes — this drives the whole UX

| Command | Time | What it does |
|---------|------|--------------|
| `python -m fnscraper best --json` | **45–75 min** | Full crawl: ~2,000 listings, geocoding, detail pages |
| `python -m fnscraper best --json --cached` | **~1 sec** | Re-plans from the last crawl, no network |

A full run is far too slow for an HTTP request. Design for this from the
start — see §4.

### Provided TypeScript

Two files, already written and type-checked under `strict`. Use them; do
not reimplement.

- **`runExport.ts`** — `runExport(options): Promise<ExportResult>`. Spawns
  the scraper, streams progress to an `onProgress` callback, resolves with
  the parsed rows.
- **`festivalImport.ts`** — `parseShowCsv(text): Show[]`. RFC-4180 reader,
  strict header validation, typed output. Throws `ShowImportError`.

```ts
import { runExport } from '@/integrations/josemadridsalsa/runExport'

const result = await runExport({
  projectDir: process.env.FNSCRAPER_DIR!,
  months: 3,
  top: 5,
  cached: false,
  onProgress: (line) => job.log(line),
})
// result.rows is Show[], already parsed and typed
```

## 2. What to build

1. A **"Find Shows"** button in the admin panel that triggers a full run.
2. A **"Refresh Rankings"** button that runs with `cached: true`.
3. A **job record** so a run survives a page reload and its progress is visible.
4. **Persistence** of the resulting shows, upserted on the show URL.
5. A **table view** of the shows, grouped by weekend.
6. A **download link** for the raw CSV.

## 3. Data model

The full field-by-field contract is in **`IMPORT_FORMAT.md`** beside this
file. Read it before writing the schema — it specifies the exact format of
all 20 columns.

Three things it will tell you that are easy to get wrong, repeated here
because they cause silent data corruption:

- **A trailing `*` means the value is an estimate**, not published by the
  promoter. It appears on Booth Fee, Attendance, and # of Exhibitors. Store
  the flag — do not discard it. The UI must show it, because those shows
  need confirming before anyone commits money.
- **An empty cell means "not published", never zero.** Do not coerce blanks
  to `0`. (Only `Lodging` of `$0.00` is a genuine zero — a day trip.)
- **`Application Deadline` is not always a date.** It can read `until full`
  or `Not listed`. Store a nullable date *and* the original text.

Suggested schema (also in `IMPORT_FORMAT.md` §6):

```sql
CREATE TABLE shows (
  url                       TEXT PRIMARY KEY,   -- natural key
  event_name                TEXT NOT NULL,
  venue                     TEXT,
  address                   TEXT,
  city                      TEXT NOT NULL,
  state                     CHAR(2) NOT NULL,
  drive_minutes             INTEGER,
  start_date                DATE NOT NULL,
  end_date                  DATE NOT NULL,
  times                     TEXT,
  application_deadline      DATE,
  application_deadline_text TEXT NOT NULL,
  booth_fee                 NUMERIC(10,2),
  booth_fee_estimated       BOOLEAN NOT NULL DEFAULT FALSE,
  attendance                INTEGER,
  attendance_estimated      BOOLEAN NOT NULL DEFAULT FALSE,
  exhibitors                INTEGER,
  exhibitors_estimated      BOOLEAN NOT NULL DEFAULT FALSE,
  fuel_cost                 NUMERIC(10,2),
  lodging_cost              NUMERIC(10,2),
  meals_cost                NUMERIC(10,2),
  contact_name              TEXT,
  contact_email             TEXT,
  application_info          TEXT,
  imported_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Upsert on `url`.** Never key on `event_name` — names repeat across years
and across the monthly variants of one series ("Bristol Renaissance Faire -
August" vs "- September").

The `Show` interface in `festivalImport.ts` already maps 1:1 to this.

## 4. Architecture — the one constraint that matters

**A full run takes 45–75 minutes. It cannot happen inside an HTTP request.**
Serverless functions cap out long before that, and even on a long-lived
server the user's browser will not wait.

Required shape:

```
POST /api/shows/refresh   ->  create job row (status=queued), return job id
                              202 Accepted, do NOT block

  background worker       ->  runExport({ onProgress: line => append log })
                              on success: upsert rows, status=complete
                              on failure: status=failed, store stderr tail

GET  /api/shows/jobs/:id  ->  { status, progress[], shows, weekends, error }
                              poll every few seconds, or use SSE
```

Use whatever job runner the site already has. If there is none, the
simplest correct option is a `jobs` table plus a detached worker process —
avoid pushing this into a request handler "for now", because it will time
out in production and the failure looks like a hang.

**Guard against concurrent runs.** Two full crawls at once will hammer
FestivalNet and may get the account rate-limited. Before starting, refuse
if a job is already `queued` or `running`.

The `--cached` path *is* fast enough for a request handler (~1 s), so the
"Refresh Rankings" button can be a plain synchronous route.

## 5. Environment

```bash
FNSCRAPER_DIR=/srv/festivalnetwork-scraper   # checkout path
PYTHON_BIN=python3                           # optional, defaults to python3
```

The scraper needs its own `.env` inside `FNSCRAPER_DIR`:

```
FESTIVALNET_USER=...
FESTIVALNET_PASS=...
```

Those are FestivalNet Pro credentials. **Without them the data is markedly
worse** — no promoter emails, no real booth fees, no application deadlines.
If the run produces rows where `contact_email` is empty across the board,
the login is failing; surface that rather than importing the degraded data
silently.

Do not commit `.env`. Do not expose these to the browser. Everything here
is server-side only — `runExport.ts` spawns a process and must never be
imported into client code.

## 6. UI notes

Group the table by weekend; that is how the plan is meant to be read — five
candidates per weekend, pick one. Suggested columns:

`Event Name · City, ST · Drive-Time · Start–End · Booth Fee · Attendance · Application Deadline · Contact`

- Badge anything with a `*` as **"estimated"**. This is the single most
  important UI affordance: it separates confirmed economics from modelled
  ones.
- Highlight deadlines inside 14 days.
- Make `contact_email` a `mailto:` and the FestivalNet URL an external link.
- Show `application_info` — it says how to actually get the form.
- Sort within a weekend by the order the CSV gives; it is already ranked
  best-first.

## 7. Acceptance criteria

- [ ] "Find Shows" starts a background job and returns immediately
- [ ] Progress is visible while it runs and survives a page reload
- [ ] A second run is refused while one is in flight
- [ ] Completed runs upsert on `url` — re-running does not duplicate rows
- [ ] `booth_fee_estimated` / `attendance_estimated` / `exhibitors_estimated` are stored and shown
- [ ] Empty cells are stored as `NULL`, not `0` or `""`
- [ ] `Application Deadline` of `until full` imports without error
- [ ] A malformed CSV fails the whole import rather than partially applying
- [ ] Failures surface the stderr tail, not a generic 500
- [ ] "Refresh Rankings" (`cached: true`) returns in about a second
- [ ] The raw CSV is downloadable
- [ ] `runExport.ts` is never bundled into client-side code

## 8. Do not

- **Do not modify anything under `fnscraper/`.** It is tested (151 tests);
  changing the scoring model or CSV columns from the web layer will break
  the contract this brief depends on.
- **Do not reimplement CSV parsing.** Use `parseShowCsv`. It handles the
  BOM, CRLF, RFC-4180 quoting, and the estimate markers, and it rejects a
  shifted header instead of importing garbage.
- **Do not run the crawl on a schedule more than once a day.** The listings
  do not change that fast and the scraper is deliberately rate-limited to
  stay a polite client.
- **Do not treat the `*` estimates as facts** anywhere in the UI. They are
  model output. A `$750.00*` tier guess against a real $2,000 state-fair
  booth fee is the difference between a profitable weekend and a loss.
