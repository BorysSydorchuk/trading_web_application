import { Link } from 'react-router'
import { formatPct } from '@/features/dashboard/format'
import { formatR, formatSignedMoney, pnlClass } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { useDigestList } from './api'
import { digestPagePath, formatDateBrussels, formatPeriod } from './format'
import { LoadErrorNote, LoadingNote } from './StateViews'
import type { DigestKind, DigestListItem } from './types'

const l = uk.digests.list
const col = l.columns
const EMPTY = uk.common.empty
const TH = 'px-3 py-2 font-medium whitespace-nowrap'
const TD = 'px-3 py-1.5 whitespace-nowrap'
const NUM = `${TD} num text-right`

/** Digests of one kind, newest first, incl. virtual rows (periods with trades but no digest yet). */
export function DigestList({ kind }: { kind: DigestKind }) {
  const list = useDigestList(kind)
  if (list.data === undefined) {
    if (list.isPending) return <LoadingNote text={l.loading} />
    return <LoadErrorNote text={l.loadError} error={list.error} onRetry={() => void list.refetch()} busy={list.isFetching} />
  }
  const items = list.data.items
  if (items.length === 0) {
    return <p className="rounded-lg border border-dashed px-4 py-6 text-center text-sm text-muted-foreground">{l.empty}</p>
  }
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table aria-label={uk.digests.kinds[kind]} className="w-full text-sm">
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            <th scope="col" className={`${TH} text-left`}>{col.period}</th>
            <th scope="col" className={`${TH} text-right`}>{col.trades}</th>
            <th scope="col" className={`${TH} text-right`}>{col.netPnl}</th>
            <th scope="col" className={`${TH} text-right`}>{col.pct}</th>
            <th scope="col" className={`${TH} text-right`}>{col.totalR}</th>
            <th scope="col" className={`${TH} text-right`}>{col.winRate}</th>
            <th scope="col" className={`${TH} text-left`}>{col.state}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <DigestRow key={`${item.period_start}:${item.id ?? 'virtual'}`} item={item} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function DigestRow({ item }: { item: DigestListItem }) {
  return (
    <tr data-virtual={item.id === null ? 'true' : undefined} className="border-t hover:bg-muted/30">
      <td className={TD}>
        <Link to={digestPagePath(item.kind, item.period_start)} className="font-medium underline-offset-2 hover:underline">
          {formatPeriod(item.kind, item.period_start)}
        </Link>
      </td>
      <td className={NUM}>{item.trades}</td>
      <td className={cn(NUM, pnlClass(item.net_pnl))}>{formatSignedMoney(item.net_pnl)}</td>
      <td className={cn(NUM, item.net_pnl_pct !== null && pnlClass(item.net_pnl_pct))}>
        {item.net_pnl_pct === null ? EMPTY : formatPct(item.net_pnl_pct)}
      </td>
      <td className={NUM}>{formatR(item.total_r)}</td>
      <td className={NUM}>{item.win_rate === null ? EMPTY : formatPct(item.win_rate)}</td>
      <td className={TD}>
        <ReviewBadge item={item} />
      </td>
    </tr>
  )
}

function ReviewBadge({ item }: { item: DigestListItem }) {
  if (item.reviewed) {
    const text = item.reviewed_at ? l.reviewed(formatDateBrussels(item.reviewed_at)) : uk.digests.page.reviewed
    return <span className="text-xs text-muted-foreground">{text}</span>
  }
  return <span className="rounded-full border border-primary/50 px-2 py-0.5 text-xs">{l.notReviewed}</span>
}
