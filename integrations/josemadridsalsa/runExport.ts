/**
 * "Find my next 3 months of shows" button.
 *
 * Runs the scraper, then parses the CSV it produced.  The scraper prints a
 * JSON summary on stdout with `--json`; everything else (progress, warnings)
 * goes to stderr, so stdout is safe to parse.
 *
 * Node 18+ / Next.js route handler — server side only, never the browser.
 */

import { spawn } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

import { parseShowCsv, type Show } from './festivalImport'

export interface ExportSummary {
  /** Path to the generated CSV, relative to the scraper's working directory. */
  csv: string
  /** Path to the column spec written beside it. */
  spec: string
  shows: number
  weekends: number
  firstWeekend: string
  lastWeekend: string
  columns: string[]
}

export interface ExportResult extends ExportSummary {
  rows: Show[]
  /** Raw CSV text — hand straight to a download response if you want. */
  csvText: string
}

export interface RunExportOptions {
  /** Checkout root of the scraper repo. */
  projectDir: string
  /** Months of weekends to plan. Default 3. */
  months?: number
  /** Shows per weekend. Default 5. */
  top?: number
  /**
   * Skip the network and re-plan from the last scrape's saved results.
   * Returns in about a second; use it for a "regenerate" button.
   */
  cached?: boolean
  /** Python executable. Default `python3`. */
  python?: string
  /** Give up after this many ms. Default 30 minutes — a full crawl is slow. */
  timeoutMs?: number
  /** Called with each line of scraper progress, for a live status UI. */
  onProgress?: (line: string) => void
}

/**
 * Run the scraper and return the parsed booking plan.
 *
 * ```ts
 * const result = await runExport({ projectDir: '/srv/festivalnetwork-scraper' })
 * console.log(`${result.shows} shows across ${result.weekends} weekends`)
 * await db.shows.upsertMany(result.rows)   // natural key: row.url
 * ```
 */
export function runExport(options: RunExportOptions): Promise<ExportResult> {
  const {
    projectDir,
    months = 3,
    top = 5,
    cached = false,
    python = 'python3',
    timeoutMs = 30 * 60 * 1000,
    onProgress,
  } = options

  const args = [
    '-m', 'fnscraper', 'best',
    '--months', String(months),
    '--top', String(top),
    '--json',
  ]
  if (cached) args.push('--cached')

  return new Promise<ExportResult>((resolve, reject) => {
    const child = spawn(python, args, {
      cwd: projectDir,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    })

    let stdout = ''
    let stderr = ''
    let settled = false

    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      child.kill('SIGTERM')
      reject(new Error(`Scraper timed out after ${timeoutMs}ms`))
    }, timeoutMs)

    child.stdout.setEncoding('utf8')
    child.stdout.on('data', (chunk: string) => {
      stdout += chunk
    })

    child.stderr.setEncoding('utf8')
    child.stderr.on('data', (chunk: string) => {
      stderr += chunk
      if (onProgress) {
        for (const line of chunk.split('\n')) {
          if (line.trim()) onProgress(line.trim())
        }
      }
    })

    child.on('error', (error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(error)
    })

    child.on('close', (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)

      if (code !== 0) {
        const detail = stderr.trim().split('\n').slice(-5).join('\n')
        reject(new Error(`Scraper exited with code ${code}\n${detail}`))
        return
      }

      let summary: ExportSummary
      try {
        const raw = JSON.parse(stdout.trim()) as Record<string, unknown>
        summary = {
          csv: raw.csv as string,
          spec: raw.spec as string,
          shows: raw.shows as number,
          weekends: raw.weekends as number,
          firstWeekend: raw.first_weekend as string,
          lastWeekend: raw.last_weekend as string,
          columns: raw.columns as string[],
        }
      } catch {
        reject(new Error(`Could not read the scraper's summary: ${stdout.slice(0, 400)}`))
        return
      }

      readFile(path.resolve(projectDir, summary.csv), 'utf8')
        .then((csvText) => {
          resolve({ ...summary, csvText, rows: parseShowCsv(csvText) })
        })
        .catch(reject)
    })
  })
}
