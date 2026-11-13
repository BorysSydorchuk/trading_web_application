/**
 * Digest display (docs/api.md "## M6", DECISIONS 2026-11-13): percents and R 2 dp, money 2 dp,
 * U+2212 minus; norms as «норма 62.50 ± 12.50»; dates in Europe/Brussels. No float math on values.
 */
import { formatMonth, formatPct, formatWeekRange } from '@/features/dashboard/format'
import { formatR, formatRatio, formatSignedMoney } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { formatDecimal, roundDecimal, trimDecimal } from '@/lib/decimal'
import { addDays, APP_TIME_ZONE, startOfMonth, startOfWeek } from '@/lib/time'
import type { DigestKind, MetricName, MetricValue, RBucket } from './types'

const EMPTY = uk.common.empty
const c = uk.digests.charts

const COUNT_METRICS: ReadonlySet<MetricName> = new Set(['trades', 'wins', 'losses', 'breakeven', 'violations'])
const MONEY_METRICS: ReadonlySet<MetricName> = new Set(['net_pnl', 'max_drawdown'])
const PCT_METRICS: ReadonlySet<MetricName> = new Set(['net_pnl_pct', 'max_drawdown_pct', 'win_rate'])
const R_METRICS: ReadonlySet<MetricName> = new Set(['total_r', 'avg_win_r', 'avg_loss_r', 'expectancy_r'])

/** Edge buckets fold everything beyond ±3 R (backend R_CLAMP). */
const R_EDGE = '3.00'

/** 2 dp with the app minus, no unit: "-1.2345" → "−1.23". */
export function formatNumber2(value: string): string {
  return formatDecimal(roundDecimal(value, 2))
}

/** A metric value in its own format; money without the currency in tables, signed like P&L columns. */
export function formatMetric(name: MetricName, value: MetricValue['value']): string {
  if (value === null) return EMPTY
  if (typeof value === 'number' || COUNT_METRICS.has(name)) return String(value)
  if (MONEY_METRICS.has(name)) return name === 'net_pnl' ? formatSignedMoney(value) : formatNumber2(value)
  if (PCT_METRICS.has(name)) return formatPct(value)
  if (R_METRICS.has(name)) return formatR(value)
  return formatRatio(value)
}

/** «норма 62.50 ± 12.50», or null when the metric has no norm. */
export function formatNorm(metric: MetricValue): string | null {
  if (metric.norm_mean === null || metric.norm_sd === null) return null
  return uk.digests.blocks.norm(formatNumber2(metric.norm_mean), formatNumber2(metric.norm_sd))
}

/** Text colour for a deviation (green/red only for deviations and P&L). */
export function deviationClass(deviation: MetricValue['deviation']): string {
  if (deviation === 'worse') return 'text-loss'
  if (deviation === 'better') return 'text-profit'
  return ''
}

/** «Тиждень 9–15 лист. 2026» / «Місяць: листопад 2026». */
export function formatPeriod(kind: DigestKind, periodStart: string): string {
  if (kind === 'weekly') return uk.digests.period.weekly(formatWeekRange(periodStart), periodStart.slice(0, 4))
  return uk.digests.period.monthly(formatMonth(periodStart))
}

/** The start of the period that contains `date` (Monday / 1st). */
export function periodStartOf(kind: DigestKind, date: string): string {
  return kind === 'weekly' ? startOfWeek(date) : startOfMonth(date)
}

/** Next period start = the day after the (inclusive) period end. */
export function nextPeriodStart(periodEnd: string): string {
  return addDays(periodEnd, 1)
}

export function digestPagePath(kind: DigestKind, periodStart: string): string {
  return `/digests/${kind}/${periodStart}`
}

const dateFormatter = new Intl.DateTimeFormat('uk-UA', {
  timeZone: APP_TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})

/** Brussels calendar date of a UTC instant: "13.11.2026". */
export function formatDateBrussels(isoUtc: string): string {
  const date = new Date(isoUtc)
  return Number.isNaN(date.getTime()) ? isoUtc : dateFormatter.format(date)
}

/** "2026-11-16" → "16.11.2026" (a calendar date, no time zone). */
export function formatIsoDay(isoDate: string): string {
  return `${isoDate.slice(8, 10)}.${isoDate.slice(5, 7)}.${isoDate.slice(0, 4)}`
}

/**
 * Bucket label (DECISIONS 2026-11-13): the lowest edge bucket [−3, −2.5) holds every R below
 * −2.5 → «≤ −2.5»; the top edge bucket [3, 3.5) holds every R from 3 → «≥ 3»; others «0.50…1.00».
 */
export function rBucketLabel(bucket: RBucket): string {
  const lower = roundDecimal(bucket.lower, 2)
  if (lower === `-${R_EDGE}`) return c.rLow(formatDecimal(trimR(bucket.upper)))
  if (lower === R_EDGE) return c.rHigh(formatDecimal(trimR(bucket.lower)))
  return c.rRange(formatNumber2(bucket.lower), formatNumber2(bucket.upper))
}

/** "-2.5000" → "-2.5", "3.0000" → "3". */
function trimR(value: string): string {
  return trimDecimal(roundDecimal(value, 2))
}
