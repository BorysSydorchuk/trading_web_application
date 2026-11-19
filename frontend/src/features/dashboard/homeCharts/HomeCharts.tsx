import { useId, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { isApiError } from '@/api/client'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { EquityChart } from '@/features/digests/charts/EquityChart'
import { formatPercent } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import type { DashboardAccount } from '../types'
import { useHomeCharts } from './api'
import { DailyPnlChart } from './DailyPnlChart'
import { RANGE_PRESETS, loadSelection, rangeOf, saveSelection, type ChartSelection } from './range'
import { RollingChart } from './RollingChart'

const t = uk.dashboard.charts
/** The API accepts these dates only (docs/api.md M8-14). */
const MIN_DATE = '2000-01-01'
const MAX_DATE = '2100-12-31'

/** M8-14: three charts on «Головна» with a shared range and account selector. */
export function HomeCharts({ accounts }: { accounts: readonly DashboardAccount[] }) {
  const id = useId()
  const [selection, setSelectionState] = useState<ChartSelection>(loadSelection)
  const accountId = accounts.some((a) => a.id === selection.accountId) ? selection.accountId : null
  const range = rangeOf({ ...selection, accountId })
  const query = useHomeCharts(range, accountId)

  function setSelection(change: Partial<ChartSelection>) {
    const next = { ...selection, ...change }
    setSelectionState(next)
    saveSelection(next)
  }

  const data = query.data
  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={`${id}-title`} className="mr-auto text-sm font-semibold">
          {t.title}
        </h2>
        <div role="group" aria-label={t.range} className="flex flex-wrap gap-1">
          {RANGE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={selection.preset === preset}
              onClick={() => setSelection({ preset })}
              className={cn(
                'rounded-md border px-2 py-1 text-xs',
                selection.preset === preset ? 'border-primary bg-primary text-primary-foreground' : 'hover:bg-accent',
              )}
            >
              {t.presets[preset]}
            </button>
          ))}
        </div>
        <label htmlFor={`${id}-account`} className="sr-only">
          {t.account}
        </label>
        <NativeSelect
          id={`${id}-account`}
          className="h-8 text-xs"
          wrapperClassName="w-44"
          value={accountId === null ? '' : String(accountId)}
          onChange={(e) => setSelection({ accountId: e.target.value === '' ? null : Number(e.target.value) })}
        >
          <option value="">{t.allAccounts}</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </NativeSelect>
      </div>
      {selection.preset === 'custom' && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <label htmlFor={`${id}-from`}>{t.from}</label>
          <Input id={`${id}-from`} type="date" min={MIN_DATE} max={MAX_DATE} className="h-8 w-40 text-xs" value={selection.from} onChange={(e) => setSelection({ from: e.target.value })} />
          <label htmlFor={`${id}-to`}>{t.to}</label>
          <Input id={`${id}-to`} type="date" min={MIN_DATE} max={MAX_DATE} className="h-8 w-40 text-xs" value={selection.to} onChange={(e) => setSelection({ to: e.target.value })} />
          {range === null && <span className="text-muted-foreground">{t.customHint}</span>}
        </div>
      )}
      <Body query={query} data={data} />
    </section>
  )
}

function errorNote(error: unknown): string {
  if (isApiError(error) && error.code === 'mixed_currency') return t.mixedCurrency
  return `${t.loadError} ${errorText(error)}`
}

function Body({ query, data }: { query: ReturnType<typeof useHomeCharts>; data: ReturnType<typeof useHomeCharts>['data'] }) {
  if (query.isError && !data) {
    return (
      <p role="alert" className="rounded-lg border border-dashed px-4 py-3 text-sm text-destructive">
        {errorNote(query.error)}
      </p>
    )
  }
  // A failed refresh keeps the last charts, but says so (errors must be visible).
  const stale = query.isError ? (
    <p role="alert" className="text-xs text-destructive">
      {t.refreshError} {errorNote(query.error)}
    </p>
  ) : null
  if (!data) {
    if (!query.isFetching) return null
    return (
      <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t.loading}
      </div>
    )
  }
  if (data.trades === 0) {
    return (
      <div className="flex flex-col gap-2">
        {stale}
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">{t.empty}</p>
      </div>
    )
  }
  const lastPct = data.equity[data.equity.length - 1]?.cum_pct ?? null
  return (
    <div className="flex flex-col gap-2">
      {stale}
      <p className="text-xs text-muted-foreground">
        {t.summary(data.trades, data.from, data.to)}
        {lastPct !== null && ` · ${t.ofSize(formatPercent(lastPct, true))}`}
      </p>
      <div className="grid gap-3 lg:grid-cols-3">
        <EquityChart title={t.equity} points={data.equity} currency={data.currency} />
        <DailyPnlChart days={data.daily} currency={data.currency} />
        <RollingChart points={data.rolling} window={data.rolling_window} />
      </div>
    </div>
  )
}
