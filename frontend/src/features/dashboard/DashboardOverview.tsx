import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { AccountLimitsCard } from './AccountLimitsCard'
import { useDashboard } from './api'
import { DigestSuggestionCard } from './DigestSuggestionCard'
import { InboxSummary } from './InboxSummary'
import { OpenPositionsTable } from './OpenPositionsTable'
import { StopBanner } from './StopBanner'
import { SyncSummary } from './SyncSummary'
import type { Dashboard } from './types'

const d = uk.dashboard

function QuickLinks() {
  return (
    <nav aria-label={d.links.title} className="flex flex-wrap gap-2">
      <Button asChild size="sm" variant="outline"><Link to="/calculator">{d.links.calculator}</Link></Button>
      <Button asChild size="sm" variant="outline"><Link to="/inbox">{d.links.describe}</Link></Button>
    </nav>
  )
}

function DashboardData({ data }: { data: Dashboard }) {
  return (
    <>
      <section aria-labelledby="dashboard-accounts" className="flex flex-col gap-2">
        <h2 id="dashboard-accounts" className="text-sm font-semibold">{d.accounts.title}</h2>
        {data.accounts.length === 0 ? (
          <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">{d.accounts.empty}</p>
        ) : (
          <div className="grid gap-3 xl:grid-cols-2">
            {data.accounts.map((account) => <AccountLimitsCard key={account.id} account={account} />)}
          </div>
        )}
      </section>
      <div className="grid gap-3 md:grid-cols-2">
        <InboxSummary counts={data.inbox} />
        <SyncSummary />
      </div>
      <OpenPositionsTable positions={data.open_positions} />
    </>
  )
}

/** Home overview (PRD 6.10): stop banner, limits per account, inbox, sync, open positions, digest reminder. */
export function DashboardOverview() {
  const query = useDashboard()
  const { data } = query
  return (
    <div className="flex flex-col gap-4">
      {data && <StopBanner stop={data.stop} />}
      <DigestSuggestionCard />
      <QuickLinks />
      {query.isPending && <p role="status" className="text-sm text-muted-foreground">{d.loading}</p>}
      {query.isError && (
        <div role="alert" className="flex flex-col items-start gap-2 rounded-lg border border-loss/40 p-4">
          <p>{d.loadError}</p>
          <p className="text-xs text-muted-foreground">{errorText(query.error)}</p>
          {data && <p className="text-xs text-muted-foreground">{d.staleNote}</p>}
          <Button variant="outline" size="sm" disabled={query.isFetching} onClick={() => void query.refetch()}>
            {uk.common.retry}
          </Button>
        </div>
      )}
      {data && <DashboardData data={data} />}
    </div>
  )
}
