import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { useDashboard } from '@/features/dashboard/api'
import { DigestSuggestionCard } from '@/features/dashboard/DigestSuggestionCard'
import { useHomeCharts } from '@/features/dashboard/homeCharts/api'
import { loadSelection, rangeOf, saveSelection, type ChartSelection } from '@/features/dashboard/homeCharts/range'
import { FirmLimitBanner } from '@/features/dashboard/FirmLimitBanner'
import { StopBanner } from '@/features/dashboard/StopBanner'
import { useHome } from '@/features/home/api'
import { BiasStatusCard } from '@/features/home/BiasStatusCard'
import { BottomCharts } from '@/features/home/BottomCharts'
import { HeroCard } from '@/features/home/HeroCard'
import type { HeroMetric } from '@/features/home/heroSeries'
import { HomeHeader } from '@/features/home/HomeHeader'
import { KpiRow } from '@/features/home/KpiRow'
import { LimitsCard } from '@/features/home/LimitsCard'
import { NeedsDescriptionTiles } from '@/features/home/NeedsDescriptionTiles'
import { OpenPositions } from '@/features/home/OpenPositions'
import { uk } from '@/i18n/uk'
import { isApiError } from '@/api/client'
import { errorText } from '@/lib/errors'

const d = uk.dashboard

/** 409 mixed_currency (selected accounts in two currencies): ask for one account, like the charts. */
function homeErrorText(error: unknown): string {
  return isApiError(error) && error.code === 'mixed_currency' ? d.charts.mixedCurrency : errorText(error)
}

/** Inline error of a polled block: what failed, why, retry; the last data stays on screen. */
function LoadError({ title, error, stale, busy, onRetry }: { title: string; error: unknown; stale: boolean; busy: boolean; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-start gap-1.5 rounded-card border border-loss/40 bg-surface px-4 py-3">
      <p className="text-destructive">{title}</p>
      <p className="text-xs text-ink-muted">{homeErrorText(error)}</p>
      {stale && <p className="text-xs text-ink-muted">{d.staleNote}</p>}
      <Button variant="outline" size="sm" disabled={busy} onClick={onRetry}>
        {uk.common.retry}
      </Button>
    </div>
  )
}

/**
 * «Головна» (M8-10b, docs/design/home-mockup.html, top to bottom): header, hero P&L + «Ліміти»,
 * open positions, KPI toggles, «Потрібен опис», «P&L по днях» + «Форма», then the digest
 * suggestion and the bias status. One account choice (all / one) scopes the whole page.
 */
export function HomePage() {
  const [selection, setSelectionState] = useState<ChartSelection>(loadSelection)
  const [metric, setMetric] = useState<HeroMetric>('pnl')
  const dashboard = useDashboard()
  const accounts = dashboard.data?.accounts ?? []
  // Until the account list arrives the remembered choice is used as is (no extra request).
  const accountId = !dashboard.data || accounts.some((a) => a.id === selection.accountId) ? selection.accountId : null
  const range = rangeOf(selection)
  const charts = useHomeCharts(range, accountId)
  const home = useHome(accountId)
  const data = home.data

  function setSelection(change: Partial<ChartSelection>) {
    const next = { ...selection, ...change }
    setSelectionState(next)
    saveSelection(next)
  }

  return (
    <div className="flex flex-col gap-[22px]">
      <HomeHeader
        now={data?.now ?? new Date().toISOString()}
        session={data?.session ?? null}
        bias={data?.bias_today ?? null}
        accounts={accounts}
        accountId={accountId}
        onAccount={(id) => setSelection({ accountId: id })}
      />
      {dashboard.data && <FirmLimitBanner stop={dashboard.data.stop} />}
      {dashboard.data && <StopBanner stop={dashboard.data.stop} />}
      {dashboard.isError && (
        <LoadError title={d.loadError} error={dashboard.error} stale={dashboard.data !== undefined} busy={dashboard.isFetching} onRetry={() => void dashboard.refetch()} />
      )}
      {home.isError && (
        <LoadError title={uk.home.hero.homeError} error={home.error} stale={data !== undefined} busy={home.isFetching} onRetry={() => void home.refetch()} />
      )}
      <div className="grid grid-cols-3 gap-[18px]">
        <HeroCard
          metric={metric}
          onBack={() => setMetric('pnl')}
          selection={selection}
          onSelection={setSelection}
          range={range}
          charts={charts}
          home={data}
        />
        <LimitsCard
          limits={data ? data.limits : undefined}
          error={home.isError && !data ? homeErrorText(home.error) : null}
          accountCount={accounts.length}
          accountId={accountId}
        />
      </div>
      {home.isPending && <p role="status" className="text-sm text-ink-muted">{d.loading}</p>}
      {data && <OpenPositions data={data} />}
      {data && <KpiRow kpis={data.kpis} metric={metric} onPick={setMetric} />}
      <NeedsDescriptionTiles />
      <BottomCharts charts={charts.data} />
      <section aria-label={uk.home.more} className="flex flex-col gap-3">
        <DigestSuggestionCard />
        <BiasStatusCard />
      </section>
    </div>
  )
}
