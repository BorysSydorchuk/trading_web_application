import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Link } from 'react-router'
import { Pill } from '@/components/studio/Pill'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { Button } from '@/components/ui/button'
import type { ColumnKey } from '@/features/journal/columns'
import { NUMERIC_COLUMNS } from '@/features/journal/columns'
import {
  NOTICE_BOX_CLASS,
  TABLE_CARD_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_ROW_CLASS,
  TABLE_TD_CLASS,
  TABLE_TH_CLASS,
} from '@/features/journal/tableStyles'
import { useTrades } from '@/features/trades/api'
import { TradeCell } from '@/features/trades/TradeCell'
import { TradeDetailDialog } from '@/features/trades/TradeDetailDialog'
import { describePath } from '@/features/trades/links'
import { INBOX_STATUSES, type InboxStatus, type TradeQuery, type TradeRow } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { inInbox } from './api'
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
          <div key={row} className="h-10 animate-pulse rounded-tile bg-muted motion-reduce:animate-none" />
        ))}
        <span className="sr-only">{p.loading}</span>
      </div>
    )
  }
  if (isError) {
    return (
      <div role="alert" className={cn(NOTICE_BOX_CLASS, 'flex flex-col items-center gap-3')}>
        <p>{p.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  }
  if (!data.items.some(inInbox)) {
    return (
      <div className={cn(NOTICE_BOX_CLASS, 'flex min-h-32 items-center justify-center')}>
        <p className="text-muted-foreground">{p.empty}</p>
      </div>
    )
  }

  const groups = INBOX_STATUSES.map((status) => ({
    status,
    trades: data.items.filter((t) => t.status === status && inInbox(t)),
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
    <section className="flex flex-col gap-3">
      <SectionHeader title={p.groups[status]}>
        <Pill mono>{trades.length}</Pill>
        <p className="text-xs text-muted-foreground">{p.groupHints[status]}</p>
      </SectionHeader>
      <div className={TABLE_CARD_CLASS}>
        <table className="w-full text-sm">
          <thead className={TABLE_HEAD_CLASS}>
            <tr>
              {COLUMNS.map((key) => (
                <th
                  key={key}
                  scope="col"
                  className={cn(
                    TABLE_TH_CLASS,
                    NUMERIC_COLUMNS.has(key) ? 'text-right' : 'text-left',
                  )}
                >
                  {uk.trades.columns[key]}
                </th>
              ))}
              <th scope="col" className="px-3 py-2.5">
                <span className="sr-only">{uk.accounts.columns.actions}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr key={trade.id} className={cn(TABLE_ROW_CLASS, 'align-middle hover:bg-accent/60')}>
                {COLUMNS.map((key) => (
                  <td
                    key={key}
                    className={cn(
                      TABLE_TD_CLASS,
                      NUMERIC_COLUMNS.has(key) ? 'text-right whitespace-nowrap' : 'text-left',
                      key !== 'violations' && 'whitespace-nowrap',
                    )}
                  >
                    <TradeCell trade={trade} column={key} />
                  </td>
                ))}
                <td className={TABLE_TD_CLASS}>
                  <div className="flex items-center justify-end gap-3">
                    {status === 'needs_sl' ? (
                      <InitialSlForm trade={trade} />
                    ) : (
                      <Button asChild size="sm" className="h-7 text-xs">
                        <Link to={describePath(trade.id)}>{status === 'draft' ? p.continueDraft : p.describe}</Link>
                      </Button>
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
