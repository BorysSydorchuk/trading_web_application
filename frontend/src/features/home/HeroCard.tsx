import { useId } from 'react'
import { Loader2 } from 'lucide-react'
import { isApiError } from '@/api/client'
import { Card } from '@/components/studio/Card'
import { SegmentedControl } from '@/components/studio/SegmentedControl'
import { Input } from '@/components/ui/input'
import type { useHomeCharts } from '@/features/dashboard/homeCharts/api'
import { RANGE_PRESETS, type ChartSelection, type RangePreset } from '@/features/dashboard/homeCharts/range'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { HeroChart } from './HeroChart'
import { kpiView, periodTitle, pnlView, type HeroMetric, type HeroView, type ValueTone } from './heroSeries'
import type { HomeData } from './types'

const t = uk.home.hero
const c = uk.dashboard.charts
/** The charts API accepts these dates only (docs/api.md M8-14). */
const MIN_DATE = '2000-01-01'
const MAX_DATE = '2100-12-31'

const TOTAL_TONE: Record<ValueTone, string> = {
  profit: 'text-profit',
  loss: 'text-loss',
  accent: 'text-lavender',
  neutral: 'text-ink',
}

const RANGE_OPTIONS = RANGE_PRESETS.map((value) => ({ value, label: t.ranges[value] }))

type ChartsQuery = ReturnType<typeof useHomeCharts>

export interface HeroCardProps {
  metric: HeroMetric
  onBack: () => void
  selection: ChartSelection
  onSelection: (change: Partial<ChartSelection>) => void
  range: { from: string; to: string } | null
  charts: ChartsQuery
  home: HomeData | undefined
}

function chartsError(error: unknown): string {
  if (isApiError(error) && error.code === 'mixed_currency') return c.mixedCurrency
  return `${c.loadError} ${errorText(error)}`
}

function Note({ children, alert = false }: { children: string; alert?: boolean }) {
  return (
    <p role={alert ? 'alert' : undefined} className={cn('flex h-[290px] items-center justify-center text-sm', alert ? 'text-destructive' : 'text-ink-muted')}>
      {children}
    </p>
  )
}

function Loading() {
  return (
    <div role="status" className="flex h-[290px] items-center justify-center gap-2 text-sm text-ink-muted">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
      {c.loading}
    </div>
  )
}

function ViewChart({ view }: { view: HeroView }) {
  const first = view.points[0]
  const last = view.points[view.points.length - 1]
  if (!first || !last) return <Note>{view.empty}</Note>
  const min = view.points.reduce((a, b) => (b.value < a.value ? b : a), first)
  return (
    <HeroChart
      points={view.points}
      xLabels={view.xLabels}
      kind={view.kind}
      format={view.format}
      ariaLabel={t.chartLabel(view.title, view.format(first.raw), view.format(last.raw), view.format(min.raw))}
      zeroLabel={view.kind === 'max_loss' ? t.maxLossLimitLine : undefined}
    />
  )
}

function PnlBody({ charts, view }: { charts: ChartsQuery; view: HeroView }) {
  if (charts.isError && !charts.data) return <Note alert>{chartsError(charts.error)}</Note>
  if (!charts.data) return charts.isFetching ? <Loading /> : <Note>{c.customHint}</Note>
  return (
    <>
      {charts.isError && (
        <p role="alert" className="mt-2 text-xs text-destructive">
          {c.refreshError} {chartsError(charts.error)}
        </p>
      )}
      {charts.data.trades === 0 ? <Note>{view.empty}</Note> : <ViewChart view={view} />}
    </>
  )
}

/** Hero card (span 2): P&L curve for the chosen range, or the KPI metric picked below. */
export function HeroCard({ metric, onBack, selection, onSelection, range, charts, home }: HeroCardProps) {
  const id = useId()
  const isPnl = metric === 'pnl'
  const view = isPnl || !home ? pnlView(charts.data, periodTitle(selection, range), selection.preset) : kpiView(metric, home)
  return (
    <Card variant="hero" aria-labelledby={`${id}-title`} className="col-span-2 rounded-[22px] px-[26px] pt-6 pb-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 id={`${id}-title`} className="text-xs tracking-[0.14em] text-ink-muted uppercase">
            {view.title}
          </h2>
          <div className="mt-2 flex flex-wrap items-baseline gap-3">
            <p data-testid="hero-total" className={cn('type-hero', TOTAL_TONE[view.totalTone])}>
              {view.total}
            </p>
            {view.sub && <p className="num text-base text-ink-muted">{view.sub}</p>}
          </div>
        </div>
        {isPnl ? (
          <div className="flex flex-col items-end gap-1.5">
            <SegmentedControl<RangePreset>
              label={t.range}
              value={selection.preset}
              options={RANGE_OPTIONS}
              onChange={(preset) => onSelection({ preset })}
            />
            {view.note && (
              <p data-testid="hero-data-from" className="num text-xs text-ink-muted">
                {view.note}
              </p>
            )}
          </div>
        ) : (
          <button
            type="button"
            onClick={onBack}
            className="rounded-xl border border-line bg-surface/80 px-3.5 py-2 text-[13px] font-semibold text-lavender outline-none hover:bg-surface focus-visible:ring-[3px] focus-visible:ring-ring"
          >
            {t.back}
          </button>
        )}
      </div>
      {isPnl && selection.preset === 'custom' && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <label htmlFor={`${id}-from`}>{c.from}</label>
          <Input id={`${id}-from`} type="date" min={MIN_DATE} max={MAX_DATE} className="h-8 w-40 bg-surface text-xs" value={selection.from} onChange={(e) => onSelection({ from: e.target.value })} />
          <label htmlFor={`${id}-to`}>{c.to}</label>
          <Input id={`${id}-to`} type="date" min={MIN_DATE} max={MAX_DATE} className="h-8 w-40 bg-surface text-xs" value={selection.to} onChange={(e) => onSelection({ to: e.target.value })} />
          {range === null && <span className="text-ink-muted">{c.customHint}</span>}
        </div>
      )}
      {isPnl ? <PnlBody charts={charts} view={view} /> : <ViewChart view={view} />}
    </Card>
  )
}
