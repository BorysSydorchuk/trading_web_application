import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ColumnKey } from '@/features/journal/columns'
import { NUMERIC_COLUMNS } from '@/features/journal/columns'
import { useTrades } from '@/features/trades/api'
import { TradeCell } from '@/features/trades/TradeCell'
import { TradeDetailDialog } from '@/features/trades/TradeDetailDialog'
import { INBOX_STATUSES, type InboxStatus, type TradeQuery, type TradeRow } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { InitialSlForm } from './InitialSlForm'

const p = uk.inboxPage

const INBOX_LIMIT = 500
/** Fallback polling; normally the list refreshes as soon as the inbox counts change. */
const INBOX_POLL_MS = 60_000
const INBOX_QUERY: TradeQuery = {
  status: [...INBOX_STATUSES],
  sort: 'close_time',
  order: 'desc',
  limit: INBOX_LIMIT,
}

const COLUMNS: readonly ColumnKey[] = [
  'close_time',
  'account',
  'symbol',
  'direction',
  'volume',
  'entry_price',
  'exit_price',
  'net_pnl',
  'violations',
]

/** Trades waiting for the user, grouped by status (needs SL first), newest first. */
export function InboxList() {
  const { data, isPending, isError, error, refetch, isFetching } = useTrades(INBOX_QUERY, { refetchInterval: INBOX_POLL_MS })
  const [openId, setOpenId] = useState<number | null>(null)

  if (isPending) {
    return (
      <div className="flex flex-col gap-2" role="status" aria-label={p.loading}>
        {[0, 1, 2].map((row) => (
          <div key={row} className="h-10 animate-pulse rounded-md bg-muted/50" />
        ))}
        <span className="sr-only">{p.loading}</span>
      </div>
    )
  }
  if (isError) {
    return (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p>{p.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  }
  if (data.items.length === 0) {
    return (
      <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center">
        <p className="text-muted-foreground">{p.empty}</p>
      </div>
    )
  }

  const groups = INBOX_STATUSES.map((status) => ({
    status,
    trades: data.items.filter((t) => t.status === status),
  })).filter((g) => g.trades.length > 0)

  return (
    <div className="flex flex-col gap-6">
      {data.total > data.items.length && (
        <p className="text-xs text-muted-foreground">{p.truncated(data.items.length, data.total)}</p>
      )}
      {groups.map((group) => (
        <InboxGroup key={group.status} status={group.status} trades={group.trades} onOpen={setOpenId} />
      ))}
      <TradeDetailDialog tradeId={openId} onClose={() => setOpenId(null)} />
    </div>
  )
}

interface InboxGroupProps {
  status: InboxStatus
  trades: TradeRow[]
  onOpen: (id: number) => void
}

function InboxGroup({ status, trades, onOpen }: InboxGroupProps) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline gap-3">
        <h2 className="text-base font-semibold">{p.groups[status]}</h2>
        <span className="num text-xs text-muted-foreground">{trades.length}</span>
        <p className="text-xs text-muted-foreground">{p.groupHints[status]}</p>
      </div>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/40 text-xs text-muted-foreground">
            <tr>
              {COLUMNS.map((key) => (
                <th
                  key={key}
                  scope="col"
                  className={cn(
                    'px-3 py-2 font-medium whitespace-nowrap',
                    NUMERIC_COLUMNS.has(key) ? 'text-right' : 'text-left',
                  )}
                >
                  {uk.trades.columns[key]}
                </th>
              ))}
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">{uk.accounts.columns.actions}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id} className="border-t align-middle hover:bg-muted/20">
                {COLUMNS.map((key) => (
                  <td
                    key={key}
                    className={cn(
                      'px-3 py-1.5',
                      NUMERIC_COLUMNS.has(key) ? 'text-right whitespace-nowrap' : 'text-left',
                      key !== 'violations' && 'whitespace-nowrap',
                    )}
                  >
                    <TradeCell trade={trade} column={key} />
                  </td>
                ))}
                <td className="px-3 py-1.5">
                  <div className="flex items-center justify-end gap-3">
                    {status === 'needs_sl' ? (
                      <InitialSlForm trade={trade} />
                    ) : (
                      <span className="text-xs whitespace-nowrap text-muted-foreground">{p.descriptionLater}</span>
                    )}
                    <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => onOpen(trade.id)}>
                      {p.details}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
