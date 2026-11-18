import { Link } from 'react-router'
import { INBOX_POLL_MS } from '@/features/inbox/api'
import { useTrades } from '@/features/trades/api'
import { formatSignedMoney } from '@/features/trades/format'
import { describePath } from '@/features/trades/links'
import type { TradeQuery } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { formatShortDateTimeBrussels } from '@/lib/time'

const n = uk.dashboard.needsDescription
const c = n.columns
/** Rows on Home; the rest is one click away in the Journal. */
export const HOME_NEEDS_DESCRIPTION_LIMIT = 10
/** Same rule as the inbox «Без опису» count: needs_description, counted in statistics (M8-01),
 * active (not archived) accounts. */
const QUERY: TradeQuery = {
  status: ['needs_description'],
  excluded: false,
  archived: false,
  sort: 'close_time',
  order: 'desc',
  limit: HOME_NEEDS_DESCRIPTION_LIMIT,
  offset: 0,
}

const TH = 'px-3 py-2 font-medium whitespace-nowrap'
const TD = 'px-3 py-1.5 whitespace-nowrap'

/** M8-15: «Потрібен опис» on Home — closed trades waiting for a description, newest first. */
export function NeedsDescriptionList() {
  const query = useTrades(QUERY, { refetchInterval: INBOX_POLL_MS })
  const items = query.data?.items ?? []
  const total = query.data?.total ?? 0
  return (
    <section aria-labelledby="dashboard-needs-description" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="dashboard-needs-description" className="text-sm font-semibold">{n.title}</h2>
        {total > items.length && (
          <Link to="/journal?status=needs_description&excluded=hide" className="text-xs text-muted-foreground underline-offset-2 hover:underline">
            {n.all(total)}
          </Link>
        )}
      </div>
      {query.isPending ? (
        <p role="status" className="text-xs text-muted-foreground">{n.loading}</p>
      ) : query.isError ? (
        <p role="alert" className="rounded-lg border border-dashed px-4 py-3 text-sm text-destructive">
          {n.error} {errorText(query.error)}
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">{n.empty}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table aria-label={n.title} className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className={`${TH} text-left`}>{c.account}</th>
                <th scope="col" className={`${TH} text-left`}>{c.symbol}</th>
                <th scope="col" className={`${TH} text-right`}>{c.closeTime}</th>
                <th scope="col" className={`${TH} text-right`}>{c.pnl}</th>
                <th scope="col" className={TH}>
                  <span className="sr-only">{c.actions}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((trade) => (
                <tr key={trade.id} className="border-t">
                  <td className={TD}>{trade.account_name}</td>
                  <td className={`${TD} font-medium`}>{trade.symbol}</td>
                  <td className={`${TD} num text-right`}>
                    {trade.close_time ? formatShortDateTimeBrussels(trade.close_time) : uk.common.empty}
                  </td>
                  <td className={`${TD} num text-right`}>{formatSignedMoney(trade.net_pnl)}</td>
                  <td className={`${TD} text-right`}>
                    <Link
                      to={describePath(trade.id)}
                      aria-label={n.describeLabel(trade.symbol, trade.close_time ? formatShortDateTimeBrussels(trade.close_time) : '')}
                      className="text-xs font-medium text-primary underline-offset-2 hover:underline"
                    >
                      {n.describe}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
