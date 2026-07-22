/**
 * Jose Madrid Salsa — festival show import.
 *
 * The scraper writes one CSV per export:
 *
 *   reports/josemadridsalsa/export<MMDDYY>-<MMDDYY>/export<MMDDYY>-<MMDDYY>.csv
 *
 * Column order is fixed and documented in the SPEC.md written beside each
 * CSV.  `SHOW_COLUMNS` below is the contract — keep it in sync with
 * `fnscraper/best.py::COLUMNS`.
 */

export const SHOW_COLUMNS = [
  'Event Name',
  'Venue',
  'Address',
  'City',
  'ST',
  'Drive-Time',
  'Start Date',
  'End Date',
  'Times',
  'Application Deadline',
  'Booth Fee',
  'Attendance',
  '# of Exhibitors',
  'Cost of Fuel',
  'Lodging',
  'Meals',
  'Contact Name',
  'Contact Email Address',
  'Application Information',
  'URL of Festivalnet posting',
] as const

export type ShowColumn = (typeof SHOW_COLUMNS)[number]

/** A row after parsing. Values the scraper could not confirm are `null`. */
export interface Show {
  eventName: string
  venue: string
  address: string
  city: string
  state: string
  /** One-way drive time from Zanesville, OH, in minutes. */
  driveMinutes: number | null
  /** ISO `YYYY-MM-DD`. */
  startDate: string
  endDate: string
  times: string
  /** ISO date when the promoter published one, else their wording. */
  applicationDeadline: string | null
  applicationDeadlineText: string
  boothFee: number | null
  attendance: number | null
  exhibitors: number | null
  fuelCost: number | null
  lodgingCost: number | null
  mealsCost: number | null
  contactName: string
  contactEmail: string
  applicationInformation: string
  /** Stable natural key — upsert on this, not on the name. */
  url: string
  /** Fields the scraper estimated rather than read off the listing. */
  estimated: {
    boothFee: boolean
    attendance: boolean
    exhibitors: boolean
  }
  /** Out-of-pocket total: booth + fuel + lodging + meals. */
  totalCost: number
}

const ESTIMATE_MARK = '*'

/** `"$1,234.50*"` / `"$150.00* (Contact)"` -> 1234.5 / 150. */
function parseMoney(raw: string): { value: number | null; estimated: boolean } {
  const text = raw.trim()
  if (!text) return { value: null, estimated: false }
  const estimated = text.includes(ESTIMATE_MARK)
  const match = text.match(/-?[\d,]+(?:\.\d+)?/)
  if (!match) return { value: null, estimated }
  const value = Number.parseFloat(match[0].replace(/,/g, ''))
  return { value: Number.isFinite(value) ? value : null, estimated }
}

/** `"2,500*"` -> 2500. */
function parseCount(raw: string): { value: number | null; estimated: boolean } {
  const text = raw.trim()
  if (!text) return { value: null, estimated: false }
  const estimated = text.includes(ESTIMATE_MARK)
  const match = text.match(/[\d,]+/)
  if (!match) return { value: null, estimated }
  const value = Number.parseInt(match[0].replace(/,/g, ''), 10)
  return { value: Number.isFinite(value) ? value : null, estimated }
}

/** `"3h 42m"` -> 222 minutes. */
export function parseDriveTime(raw: string): number | null {
  const match = raw.trim().match(/^(\d+)h\s*(\d+)m$/)
  if (!match) return null
  return Number.parseInt(match[1], 10) * 60 + Number.parseInt(match[2], 10)
}

/** `"09/12/2026"` -> `"2026-09-12"`. Returns null for anything else. */
export function parseUsDate(raw: string): string | null {
  const match = raw.trim().match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (!match) return null
  const [, month, day, year] = match
  return `${year}-${month}-${day}`
}

/**
 * RFC-4180 CSV reader: handles quoted fields, escaped `""`, embedded commas
 * and newlines, a UTF-8 BOM, and both CRLF and LF endings.
 */
export function parseCsv(text: string): string[][] {
  const input = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false

  for (let i = 0; i < input.length; i += 1) {
    const char = input[i]
    if (quoted) {
      if (char === '"') {
        if (input[i + 1] === '"') {
          field += '"'
          i += 1
        } else {
          quoted = false
        }
      } else {
        field += char
      }
      continue
    }
    if (char === '"') {
      quoted = true
    } else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n' || char === '\r') {
      if (char === '\r' && input[i + 1] === '\n') i += 1
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else {
      field += char
    }
  }
  if (field !== '' || row.length > 0) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

export class ShowImportError extends Error {}

/**
 * Parse an export CSV into `Show` records.
 *
 * Throws `ShowImportError` when the header does not match the expected
 * column set — better to reject the file than to silently import a column
 * shift after a format change.
 */
export function parseShowCsv(text: string): Show[] {
  const rows = parseCsv(text).filter((r) => r.some((cell) => cell.trim() !== ''))
  if (rows.length === 0) throw new ShowImportError('File is empty')

  const header = rows[0].map((h) => h.trim())
  if (header.length !== SHOW_COLUMNS.length) {
    throw new ShowImportError(
      `Expected ${SHOW_COLUMNS.length} columns, found ${header.length}`,
    )
  }
  SHOW_COLUMNS.forEach((expected, index) => {
    if (header[index] !== expected) {
      throw new ShowImportError(
        `Column ${index + 1}: expected "${expected}", found "${header[index]}"`,
      )
    }
  })

  return rows.slice(1).map((cells, rowIndex) => {
    const at = (column: ShowColumn) => (cells[SHOW_COLUMNS.indexOf(column)] ?? '').trim()

    const startDate = parseUsDate(at('Start Date'))
    if (!startDate) {
      throw new ShowImportError(
        `Row ${rowIndex + 2}: unreadable Start Date "${at('Start Date')}"`,
      )
    }
    const boothFee = parseMoney(at('Booth Fee'))
    const attendance = parseCount(at('Attendance'))
    const exhibitors = parseCount(at('# of Exhibitors'))
    const fuel = parseMoney(at('Cost of Fuel'))
    const lodging = parseMoney(at('Lodging'))
    const meals = parseMoney(at('Meals'))
    const deadlineText = at('Application Deadline')

    return {
      eventName: at('Event Name'),
      venue: at('Venue'),
      address: at('Address'),
      city: at('City'),
      state: at('ST'),
      driveMinutes: parseDriveTime(at('Drive-Time')),
      startDate,
      endDate: parseUsDate(at('End Date')) ?? startDate,
      times: at('Times'),
      applicationDeadline: parseUsDate(deadlineText),
      applicationDeadlineText: deadlineText,
      boothFee: boothFee.value,
      attendance: attendance.value,
      exhibitors: exhibitors.value,
      fuelCost: fuel.value,
      lodgingCost: lodging.value,
      mealsCost: meals.value,
      contactName: at('Contact Name'),
      contactEmail: at('Contact Email Address'),
      applicationInformation: at('Application Information'),
      url: at('URL of Festivalnet posting'),
      estimated: {
        boothFee: boothFee.estimated,
        attendance: attendance.estimated,
        exhibitors: exhibitors.estimated,
      },
      totalCost:
        (boothFee.value ?? 0) +
        (fuel.value ?? 0) +
        (lodging.value ?? 0) +
        (meals.value ?? 0),
    }
  })
}
