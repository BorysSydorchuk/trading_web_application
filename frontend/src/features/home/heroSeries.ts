/** What the hero card shows for each metric (P&L curve or one of the KPI cards, M8-10b). */
import type { HomeCharts } from '@/features/dashboard/homeCharts/api'
import type { ChartSelection, RangePreset } from '@/features/dashboard/homeCharts/range'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { formatPct, formatR, formatUsd } from '@/lib/displayFormat'
import { evenIndices, MAX_LOSS_WARN_PCT, monthBoundaryIndices } from './chartMath'
import { brusselsDayMonth, brusselsHourMinute, brusselsMonth } from './dates'
import type { ChartKind, ChartPoint } from './HeroChart'
import type { HomeData } from './types'

export const HERO_METRICS = ['pnl', 'today', 'win_rate', 'avg_r', 'max_loss'] as const
export type HeroMetric = (typeof HERO_METRICS)[number]
export type KpiMetric = Exclude<HeroMetric, 'pnl'>

const t = uk.home.hero
const k = uk.home.kpis
const X_LABELS = 4

export type ValueTone = 'profit' | 'loss' | 'accent' | 'neutral'

export interface HeroView {
  title: string
  total: string
  totalTone: ValueTone
  sub: string
  kind: ChartKind
  points: ChartPoint[]
  xLabels: { index: number; text: string }[]
  format: (value: string) => string
  /** Shown instead of the chart when there are no points. */
  empty: string
}

export const signTone = (value: string | null): ValueTone => {
  if (value === null) return 'neutral'
  const sign = decimalSign(value)
  return sign > 0 ? 'profit' : sign < 0 ? 'loss' : 'neutral'
}

const usd = (v: string) => formatUsd(v, 'overview', { signed: true })
const pctSigned = (v: string) => formatPct(v, 'overview', { signed: true })
const pct = (v: string) => formatPct(v, 'overview')
const r = (v: string) => formatR(v, 'overview')

function toPoints(raws: readonly string[]): ChartPoint[] {
  return raws.map((raw) => ({ raw, value: Number(raw) })).filter((p) => Number.isFinite(p.value))
}

function xLabels(times: readonly string[], label: (iso: string) => string) {
  return evenIndices(times.length, X_LABELS).map((index) => ({ index, text: label(times[index] ?? '') }))
}

/** Long ranges label month starts («вер», «жов»; «січ 27» when the points span years). */
const MONTH_LABEL_PRESETS: ReadonlySet<RangePreset> = new Set(['months3', 'year', 'all'])

function monthLabels(times: readonly string[]) {
  const months = times.map(brusselsMonth)
  const withYear = new Set(months.flatMap((m) => (m ? [m.year] : []))).size > 1
  const keys = months.map((m) => (m ? `${m.year}-${m.month}` : ''))
  return monthBoundaryIndices(keys).map((index) => {
    const m = months[index]
    const name = m ? (t.monthsShort[m.month - 1] ?? '') : ''
    return { index, text: m && withYear ? t.monthYear(name, String(m.year % 100).padStart(2, '0')) : name }
  })
}

/** Room to the max-loss floor: loss colour near the limit (<= 2 %), otherwise ink. */
export function maxLossTone(pct: string | null): 'loss' | 'neutral' {
  if (pct === null) return 'neutral'
  const value = Number(pct)
  return Number.isFinite(value) && value <= MAX_LOSS_WARN_PCT ? 'loss' : 'neutral'
}

/** The floor as a negative percent («−10%») whatever sign the API sends. */
export const maxLossLimit = (limitPct: string) => formatPct(`-${limitPct.replace(/^[+-]/, '')}`, 'overview', { signed: true })

function monthName(iso: string): string {
  const month = brusselsMonth(iso)
  return month ? (uk.dashboard.months[month.month - 1] ?? '') : ''
}

/** "тиждень", "листопад", "3 місяці", "01.11–10.11" ... */
export function periodTitle(selection: ChartSelection, range: { from: string; to: string } | null): string {
  if (selection.preset === 'month') return range ? monthName(`${range.from}T12:00:00Z`) : ''
  if (selection.preset === 'custom') {
    return range ? t.customPeriod(brusselsDayMonth(`${range.from}T12:00:00Z`), brusselsDayMonth(`${range.to}T12:00:00Z`)) : ''
  }
  return t.periods[selection.preset]
}

export function pnlView(charts: HomeCharts | undefined, period: string, preset: RangePreset): HeroView {
  const equity = charts?.equity ?? []
  const last = equity[equity.length - 1]
  return {
    title: t.pnlTitle(period),
    total: last ? usd(last.cum_pnl) : charts ? usd('0') : uk.common.empty,
    totalTone: signTone(last?.cum_pnl ?? null),
    sub: t.pnlSub(charts?.currency ?? '', last?.cum_pct ? pctSigned(last.cum_pct) : ''),
    kind: 'money',
    points: toPoints(equity.map((p) => p.cum_pnl)),
    xLabels: MONTH_LABEL_PRESETS.has(preset) ? monthLabels(equity.map((p) => p.time)) : xLabels(equity.map((p) => p.time), brusselsDayMonth),
    format: usd,
    empty: uk.dashboard.charts.empty,
  }
}

function maxLossView({ kpis }: HomeData): HeroView {
  const m = kpis.max_loss
  if (m === null) {
    return { title: t.maxLossTitle(''), total: uk.common.empty, totalTone: 'neutral', sub: '', kind: 'max_loss', points: [], xLabels: [], format: pct, empty: k.maxLossNoLimits }
  }
  const sub = [k.maxLossLimit(maxLossLimit(m.limit_pct)), m.equity_source === 'mt5' ? '' : k.maxLossNoFloating].filter(Boolean).join(' · ')
  return {
    title: t.maxLossTitle(m.account_name),
    total: m.pct === null ? uk.common.empty : pct(m.pct),
    totalTone: maxLossTone(m.pct),
    sub,
    kind: 'max_loss',
    points: toPoints(m.series.map((p) => p.pct)),
    xLabels: xLabels(m.series.map((p) => p.time), brusselsDayMonth),
    format: pct,
    empty: t.maxLossEmpty,
  }
}

/** One of the four KPI metrics from `GET /api/home`. */
export function kpiView(metric: KpiMetric, data: HomeData): HeroView {
  const { kpis } = data
  const currency = data.limits?.currency ?? ''
  switch (metric) {
    case 'today':
      return {
        title: t.todayTitle,
        total: usd(kpis.today.pnl),
        totalTone: signTone(kpis.today.pnl),
        sub: t.todaySub(currency, kpis.today.pct === null ? '' : pctSigned(kpis.today.pct), kpis.today.trades),
        kind: 'money',
        points: toPoints(kpis.today.series.map((p) => p.cum_pnl)),
        xLabels: xLabels(kpis.today.series.map((p) => p.time), brusselsHourMinute),
        format: usd,
        empty: t.todayEmpty,
      }
    case 'win_rate':
      return {
        title: t.winRateTitle(kpis.win_rate.window),
        total: pct(kpis.win_rate.value ?? ''),
        totalTone: 'accent',
        sub: t.winRateSub(kpis.win_rate.n),
        kind: 'rate',
        points: toPoints(kpis.win_rate.series.map((p) => p.value)),
        xLabels: xLabels(kpis.win_rate.series.map((p) => p.time), brusselsDayMonth),
        format: pct,
        empty: t.rollingEmpty,
      }
    case 'avg_r':
      return {
        title: t.avgRTitle(kpis.avg_r.window),
        total: r(kpis.avg_r.value ?? ''),
        totalTone: 'accent',
        sub: t.avgRSub,
        kind: 'r',
        points: toPoints(kpis.avg_r.series.map((p) => p.value)),
        xLabels: xLabels(kpis.avg_r.series.map((p) => p.time), brusselsDayMonth),
        format: r,
        empty: t.rollingEmpty,
      }
    case 'max_loss':
      return maxLossView(data)
  }
}
