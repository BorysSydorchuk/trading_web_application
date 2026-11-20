import { KpiCard } from '@/components/studio/KpiCard'
import type { KpiTone } from '@/components/studio/tones'
import { uk } from '@/i18n/uk'
import { formatPct, formatR, formatUsd } from '@/lib/displayFormat'
import { sparkPoints } from './chartMath'
import { signTone, type HeroMetric, type KpiMetric } from './heroSeries'
import type { HomeKpis } from './types'

const t = uk.home.kpis
const SPARK_W = 120
const SPARK_H = 26

const SPARK_STROKE: Record<KpiTone, string> = {
  profit: 'stroke-profit-strong',
  loss: 'stroke-loss-strong',
  accent: 'stroke-lavender-mid',
  neutral: 'stroke-faint',
}

function Sparkline({ values, tone }: { values: readonly number[]; tone: KpiTone }) {
  if (values.length < 2) return null
  return (
    <svg viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} aria-hidden className="h-[26px] w-full" data-testid="kpi-sparkline">
      <polyline points={sparkPoints(values, SPARK_W, SPARK_H)} fill="none" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={SPARK_STROKE[tone]} />
    </svg>
  )
}

interface KpiItem {
  metric: KpiMetric
  label: string
  value: string
  tone: KpiTone
  series: number[]
}

const numbers = (raws: readonly string[]) => raws.map(Number).filter(Number.isFinite)

function items(kpis: HomeKpis): KpiItem[] {
  const todayTone = signTone(kpis.today.pnl) === 'loss' ? 'loss' : 'profit'
  return [
    {
      metric: 'today',
      label: t.today,
      value: formatUsd(kpis.today.pnl, 'overview', { signed: true }),
      tone: todayTone,
      series: numbers(kpis.today.series.map((p) => p.cum_pnl)),
    },
    { metric: 'win_rate', label: t.winRate, value: formatPct(kpis.win_rate.value, 'overview'), tone: 'accent', series: numbers(kpis.win_rate.series.map((p) => p.value)) },
    { metric: 'avg_r', label: t.avgR, value: formatR(kpis.avg_r.value, 'overview'), tone: 'accent', series: numbers(kpis.avg_r.series.map((p) => p.value)) },
    {
      metric: 'drawdown',
      label: t.drawdown,
      value: formatPct(kpis.drawdown.pct, 'overview', { signed: true }),
      tone: 'loss',
      series: numbers(kpis.drawdown.series.map((p) => p.pct)),
    },
  ]
}

export interface KpiRowProps {
  kpis: HomeKpis
  metric: HeroMetric
  /** Picks a metric for the hero chart; picking the shown one returns to the P&L curve. */
  onPick: (metric: HeroMetric) => void
}

/** Four KPI toggle cards with sparklines; the pressed one is on the hero chart («на графіку»). */
export function KpiRow({ kpis, metric, onPick }: KpiRowProps) {
  return (
    <div role="group" aria-label={t.label} className="grid grid-cols-4 gap-4">
      {items(kpis).map((item) => {
        const selected = metric === item.metric
        return (
          <KpiCard
            key={item.metric}
            label={item.label}
            value={item.value}
            tone={item.tone}
            hint={selected ? t.hintOn : t.hintIdle}
            selected={selected}
            onClick={() => onPick(selected ? 'pnl' : item.metric)}
            sparkline={<Sparkline values={item.series} tone={item.tone} />}
          />
        )
      })}
    </div>
  )
}
