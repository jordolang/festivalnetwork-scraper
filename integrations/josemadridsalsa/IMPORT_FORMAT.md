# Show import — CSV format specification

Hand this to whoever builds the importer. It describes exactly what the
file contains and how each field must be read.

---

## 1. File format

| Property | Value |
|----------|-------|
| Encoding | UTF-8 **with BOM** (`EF BB BF`) |
| Line ending | `CRLF` (`\r\n`) |
| Quoting | RFC 4180 — a field is quoted only if it contains `,` `"` or a newline |
| Escaping | A `"` inside a quoted field is doubled (`""`) |
| Header row | **Required**, always the first line, always the 20 names below in that order |
| Row count | One row per show. 65 rows is typical for a 3-month plan |
| Filename | `export<MMDDYY>-<MMDDYY>.csv` — the first and last show date in the file |

The BOM matters: strip it before reading the first header name, or the
first column arrives as `﻿Event Name` and the header check fails.

## 2. Header row

Verbatim. Reject the file if it does not match exactly — a silent column
shift is worse than a failed import.

```
Event Name,Venue,Address,City,ST,Drive-Time,Start Date,End Date,Times,Application Deadline,Booth Fee,Attendance,# of Exhibitors,Cost of Fuel,Lodging,Meals,Contact Name,Contact Email Address,Application Information,URL of Festivalnet posting
```

Note column 13 is `# of Exhibitors` — it begins with `#` and contains
spaces. Do not let a comment-stripping CSV reader eat it.

## 3. Fields

`Req` = the field is never empty.

| # | Column | Type | Format | Req | Example |
|---|--------|------|--------|-----|---------|
| 1 | Event Name | text | free text | ✅ | `Cecil County Fair` |
| 2 | Venue | text | free text | | `Fair Hill Fairgrounds` |
| 3 | Address | text | `street, city, ST ZIP` | | `4640 Telegraph Road, Elkton, MD 21921` |
| 4 | City | text | free text | ✅ | `Elkton` |
| 5 | ST | text | 2 uppercase letters | ✅ | `MD` |
| 6 | Drive-Time | duration | `^\d+h \d{2}m$` | ✅ | `7h 04m` |
| 7 | Start Date | date | `MM/DD/YYYY` | ✅ | `07/24/2026` |
| 8 | End Date | date | `MM/DD/YYYY` | ✅ | `08/01/2026` |
| 9 | Times | text | free text | | `Sat 10am-6pm; Sun 11am-5pm` |
| 10 | Application Deadline | date **or** text | `MM/DD/YYYY`, or free text | ✅ | `08/15/2026` / `until full` |
| 11 | Booth Fee | money | `$0.00`, optional `*`, optional ` (note)` | ✅ | `$350.00` / `$750.00* (Contact)` |
| 12 | Attendance | integer | digits, optional `*` | ✅ | `80000` / `1500*` |
| 13 | # of Exhibitors | integer | digits, optional `*` | ✅ | `43` / `40*` |
| 14 | Cost of Fuel | money | `$0.00` | ✅ | `$135.35` |
| 15 | Lodging | money | `$0.00` | ✅ | `$990.00` |
| 16 | Meals | money | `$0.00` | ✅ | `$350.00` |
| 17 | Contact Name | text | person or organisation | ✅ | `Fair Office` |
| 18 | Contact Email Address | email | | | `vendorinfo@cecilcountyfair.org` |
| 19 | Application Information | text | free text | ✅ | `Email to request application` |
| 20 | URL of Festivalnet posting | url | absolute `https://` | ✅ | `https://festivalnet.com/33885/...` |

## 4. Five rules that will break the import if missed

**1. A trailing `*` means "estimated", not published.**
It appears on **Booth Fee**, **Attendance**, and **# of Exhibitors** only.
Strip it before parsing the number, and store it as a flag — those values
came from a model, not from the promoter, and should be confirmed before
committing to a show.

```
$350.00              a real published fee
$750.00*             an estimate
$750.00* (Contact)   an estimate; the listing says to ask the promoter
```

**2. An empty cell means "not published". It never means zero.**
Do not coerce blanks to `0` or `""`-as-zero. The one exception is
**Lodging**, where a real `$0.00` means the show is a day trip.

**3. `Application Deadline` is not always a date.**
Try `MM/DD/YYYY` first; on failure keep the raw string. Real values in
circulation: `until full`, `Not listed`, `See application`. Store both a
nullable date column and the original text.

**4. `URL of Festivalnet posting` is the natural key.**
It is stable across exports. Upsert on it. Do **not** key on Event Name —
names repeat across years and across the monthly variants of one series
("Bristol Renaissance Faire - August" vs "- September").

**5. Money fields carry `$` and thousands separators.**
Strip `[$,*]` and any trailing ` (...)` before converting. Values can
exceed `$1,000.00`.

## 5. Example rows

Verbatim from a real export. Note row 1 has an **empty `Times`** (field 9,
the `,,`) and a **quoted `Address`** because it contains commas.

```
Event Name,Venue,Address,City,ST,Drive-Time,Start Date,End Date,Times,Application Deadline,Booth Fee,Attendance,# of Exhibitors,Cost of Fuel,Lodging,Meals,Contact Name,Contact Email Address,Application Information,URL of Festivalnet posting
Cecil County Fair,Fair Hill Fairgrounds,"4640 Telegraph Road, Elkton, MD 21921",Elkton,MD,7h 04m,07/24/2026,08/01/2026,,until full,$350.00,80000,43,$135.35,$990.00,$350.00,Fair Office,vendorinfo@cecilcountyfair.org,View instructions at our web site,https://festivalnet.com/33885/Elkton-Maryland/State-Fairs/Cecil-County-Fair
Ohio State Fair,Ohio Expo Center,"717 E 17th Ave, Columbus, OH 43211",Columbus,OH,1h 06m,07/29/2026,08/09/2026,,05/01/2026,$750.00* (Contact),1000000,300*,$29.15,$0.00,$420.00,Vendor Office,vendors@expo.ohio.gov,Apply online,https://festivalnet.com/12345/Columbus-Ohio/State-Fairs/Ohio-State-Fair
```

Reading row 1 field by field:

| Field | Raw | Parsed |
|-------|-----|--------|
| Address | `"4640 Telegraph Road, Elkton, MD 21921"` | quoted — the commas are data |
| Drive-Time | `7h 04m` | 424 minutes, one way |
| Times | *(empty)* | not published |
| Application Deadline | `until full` | no date; keep the text |
| Booth Fee | `$350.00` | `350.00`, published |
| Lodging | `$990.00` | overnight trip |

And row 2: `$750.00* (Contact)` → `750.00`, **estimated**, promoter says to
contact them. `300*` → 300 exhibitors, **estimated**. `$0.00` lodging → a
day trip, a genuine zero.

## 6. Suggested target schema

```sql
CREATE TABLE shows (
  url                    TEXT PRIMARY KEY,   -- natural key, column 20
  event_name             TEXT NOT NULL,
  venue                  TEXT,
  address                TEXT,
  city                   TEXT NOT NULL,
  state                  CHAR(2) NOT NULL,
  drive_minutes          INTEGER,            -- from "7h 04m"
  start_date             DATE NOT NULL,
  end_date               DATE NOT NULL,
  times                  TEXT,
  application_deadline   DATE,               -- NULL when not a date
  application_deadline_text TEXT NOT NULL,   -- always the raw string
  booth_fee              NUMERIC(10,2),
  booth_fee_estimated    BOOLEAN NOT NULL DEFAULT FALSE,
  attendance             INTEGER,
  attendance_estimated   BOOLEAN NOT NULL DEFAULT FALSE,
  exhibitors             INTEGER,
  exhibitors_estimated   BOOLEAN NOT NULL DEFAULT FALSE,
  fuel_cost              NUMERIC(10,2),
  lodging_cost           NUMERIC(10,2),
  meals_cost             NUMERIC(10,2),
  contact_name           TEXT,
  contact_email          TEXT,
  application_info       TEXT,
  imported_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 7. Validation before accepting a file

1. Strip the BOM, split on `CRLF`.
2. Compare the header to the 20 names in §2 — **reject on any mismatch**.
3. Every row must have exactly 20 fields after RFC-4180 parsing.
4. `Start Date` and `End Date` must parse as `MM/DD/YYYY`; `End Date >= Start Date`.
5. `ST` must be two uppercase letters.
6. `URL of Festivalnet posting` must be absolute and unique within the file.
7. Reject the whole file on any failure rather than importing part of it —
   these are regenerated on demand, so a re-run is cheap.

A reference implementation of all of this, in TypeScript, is in
`festivalImport.ts` beside this file (`parseShowCsv`).
