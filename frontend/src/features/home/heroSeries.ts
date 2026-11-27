/** What the hero card shows for each metric (P&L curve or one of the KPI cards, M8-10b). */
import type { HomeCharts } from '@/features/dashboard/homeCharts/api'
import type { ChartSelection, RangePreset } from '@/features/dashboard/homeCharts/range'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { formatPct, formatR } from '@/lib/displayFormat'
import { addDays, brusselsToday } from '@/lib/time'
import { type AxisCandidate, dateCandidates, pointCandidates } from './axisLabels'
import { MAX_LOSS_WARN_PCT } from './chartMath'
import { brusselsDayMonth, brusselsHourMinute, brusselsMonth } from './dates'
import type { ChartKind, ChartPoint } from './HeroChart'
import type { HomeData } from './types'

export const HERO_METRICS = ['pnl', 'today', 'win_rate', 'avg_r', 'max_loss'] as const
export type HeroMetric = (typeof HERO_METRICS)[number]
export type KpiMetric = Exclude<HeroMetric, 'pnl'>

const t = uk.home.hero
const k = uk.home.kpis

export type ValueTone = 'profit' | 'loss' | 'accent' | 'neutral'

export interface HeroView {
  title: string
  total: string
  totalTone: ValueTone
  sub: string
  kind: ChartKind
  points: ChartPoint[]
  /** Date / time label candidates; the chart keeps those that fit its width. */
  xLabels: AxisCandidate[]
  /** Muted note when the data starts after the range start («дані з 28.10»), else ''. */
  note: string
  format: (value: string) => string
  /** Shown instead of the chart when there are no points. */
  empty: string
}

export const signTone = (value: string | null): ValueTone => {
  if (value === null) return 'neutral'
  const sign = decimalSign(value)
  return sign > 0 ? 'profit' : sign < 0 ? 'loss' : 'neutral'
}

const pctSigned = (v: string | null) => formatPct(v, 'overview', { signed: true })
const pct = (v: string) => formatPct(v, 'overview')
const r = (v: string) => formatR(v, 'overview')

function toPoints(raws: readonly (string | null)[]): ChartPoint[] {
  return raws
    .filter((raw): raw is string => raw !== null)
    .map((raw) => ({ raw, value: Number(raw) }))
    .filter((p) => Number.isFinite(p.value))
}

/** «середнє по рахунках» when the % averages more than one account. */
const averageNote = (accounts: number) => (accounts > 1 ? t.average : '')

/** Long ranges label month starts when the actual span is long enough (axisLabels.ts). */
const MONTH_LABEL_PRESETS: ReadonlySet<RangePreset> = new Set(['months3', 'year', 'all'])

/**
 * Times the P&L curve is labelled by: the API's start point (0 at midnight of the range start) moves
 * to the first trade, so the axis spans the actual data, not the empty part of the range.
 */
function spanTimes(equity: HomeCharts['equity']): string[] {
  const times = equity.map((p) => p.time)
  const firstTrade = times[1]
  return firstTrade === undefined ? times : [firstTrade, ...times.slice(1)]
}

/** The note shows only when the data starts at least this many days after the range start. */
const DATA_FROM_MIN_DAYS = 7

/** «дані з 28.10» when the first trade's Brussels day is a week or more after the range start. */
function dataFromNote(charts: HomeCharts | undefined): string {
  const firstTrade = charts?.equity[1]?.time
  if (!charts || charts.trades === 0 || firstTrade === undefined) return ''
  const date = new Date(firstTrade)
  if (Number.isNaN(date.getTime()) || brusselsToday(date) < addDays(charts.from, DATA_FROM_MIN_DAYS)) return ''
  return t.dataFrom(brusselsDayMonth(firstTrade))
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

/** «Головна» shows percentages only (owner 2026-11-27): the range result in % of the account size,
 *  equal-weighted over the accounts for «Усі рахунки», and the total R as the secondary value. */
export function pnlView(charts: HomeCharts | undefined, period: string, preset: RangePreset): HeroView {
  const equity = charts?.equity ?? []
  const total = charts?.total_pct ?? null
  return {
    title: t.pnlTitle(period),
    total: total !== null ? pctSigned(total) : uk.common.empty,
    totalTone: signTone(total),
    sub: charts ? t.pnlSub(charts.total_r !== null ? t.totalR(r(charts.total_r)) : '', averageNote(charts.accounts_counted)) : '',
    kind: 'money',
    points: toPoints(equity.map((p) => p.cum_pct)),
    xLabels: dateCandidates(spanTimes(equity), MONTH_LABEL_PRESETS.has(preset)),
    note: dataFromNote(charts),
    format: pctSigned,
    empty: uk.dashboard.charts.empty,
  }
}

function maxLossView({ kpis }: HomeData): HeroView {
  const m = kpis.max_loss
  if (m === null) {
    return { title: t.maxLossTitle(''), total: uk.common.empty, totalTone: 'neutral', sub: '', kind: 'max_loss', points: [], xLabels: [], note: '', format: pct, empty: k.maxLossNoLimits }
  }
  const sub = [k.maxLossLimit(maxLossLimit(m.limit_pct)), m.equity_source === 'mt5' ? '' : k.maxLossNoFloating].filter(Boolean).join(' · ')
  return {
    title: t.maxLossTitle(m.account_name),
    total: m.pct === null ? uk.common.empty : pct(m.pct),
    totalTone: maxLossTone(m.pct),
    sub,
    kind: 'max_loss',
    points: toPoints(m.series.map((p) => p.pct)),
    xLabels: pointCandidates(m.series.map((p) => p.time)),
    note: '',
    format: pct,
    empty: t.maxLossEmpty,
  }
}

/** One of the four KPI metrics from `GET /api/home`. */
export function kpiView(metric: KpiMetric, data: HomeData): HeroView {
  const { kpis } = data
  switch (metric) {
    case 'today':
      return {
        title: t.todayTitle,
        total: pctSigned(kpis.today.pct),
        totalTone: signTone(kpis.today.pct),
        sub: t.todaySub(kpis.today.trades, averageNote(kpis.today.accounts_counted)),
        kind: 'money',
        points: toPoints(kpis.today.series.map((p) => p.cum_pct)),
        xLabels: pointCandidates(kpis.today.series.map((p) => p.time), brusselsHourMinute),
        note: '',
        format: pctSigned,
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
        xLabels: pointCandidates(kpis.win_rate.series.map((p) => p.time)),
        note: '',
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
        xLabels: pointCandidates(kpis.avg_r.series.map((p) => p.time)),
        note: '',
        format: r,
        empty: t.rollingEmpty,
      }
    case 'max_loss':
      return maxLossView(data)
  }
}
