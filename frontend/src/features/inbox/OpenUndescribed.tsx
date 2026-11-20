import { Loader2 } from 'lucide-react'
import { Link } from 'react-router'
import { Pill } from '@/components/studio/Pill'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { Button } from '@/components/ui/button'
import { useHome } from '@/features/home/api'
import type { HomePosition } from '@/features/home/types'
import { directionLabel } from '@/features/trades/format'
import { TABLE_CARD_CLASS, TABLE_HEAD_CLASS, TABLE_ROW_CLASS, TABLE_TD_CLASS, TABLE_TH_CLASS } from '@/features/journal/tableStyles'
import { describePath } from '@/features/trades/links'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { formatShortDateTimeBrussels } from '@/lib/time'

const p = uk.inboxPage
const cols = uk.trades.columns
const TH = `${TABLE_TH_CLASS} text-left`
const TD = `${TABLE_TD_CLASS} whitespace-nowrap`

/**
 * M8-10b «Відкриті · можна описати зараз»: open positions of every active account without a
 * description (`GET /api/home` open_positions). Not part of the inbox counts or the sidebar badge;
 * hidden while loading and when there are none; a load error stays inline (no toast).
 */
export function OpenUndescribed() {
  const { data, isError, error, refetch, isFetching } = useHome(null)

  if (isError && !data) {
    return (
      <section aria-labelledby="inbox-open" className="flex flex-col gap-3">
        <SectionHeader id="inbox-open" title={p.open.title} />
        <div role="alert" className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{p.open.loadError} {errorText(error)}</span>
          <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => void refetch()} disabled={isFetching}>
            {isFetching && <Loader2 className="animate-spin" aria-hidden />}
            {uk.common.retry}
          </Button>
        </div>
      </section>
    )
  }

  const positions = (data?.open_positions ?? []).filter((position) => !position.described)
  if (positions.length === 0) return null

  return (
    <section aria-labelledby="inbox-open" className="flex flex-col gap-3">
      <SectionHeader id="inbox-open" title={p.open.title}>
        <Pill mono>{positions.length}</Pill>
        <p className="text-xs text-muted-foreground">{p.open.hint}</p>
      </SectionHeader>
      <div className={TABLE_CARD_CLASS}>
        <table aria-label={p.open.title} className="w-full text-sm">
          <thead className={TABLE_HEAD_CLASS}>
            <tr>
              <th scope="col" className={TH}>{cols.open_time}</th>
              <th scope="col" className={TH}>{cols.account}</th>
              <th scope="col" className={TH}>{cols.symbol}</th>
              <th scope="col" className={TH}>{cols.direction}</th>
              <th scope="col" className="px-3 py-2.5">
                <span className="sr-only">{uk.accounts.columns.actions}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {positions.map((position) => (
              <OpenRow key={position.trade_id} position={position} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function OpenRow({ position }: { position: HomePosition }) {
  return (
    <tr className={`${TABLE_ROW_CLASS} align-middle hover:bg-accent/60`}>
      <td className={`${TD} num`}>{formatShortDateTimeBrussels(position.open_time)}</td>
      <td className={TD}>{position.account_name}</td>
      <td className={`${TD} num`}>{position.symbol}</td>
      <td className={TD}>{directionLabel(position.direction)}</td>
      <td className={TABLE_TD_CLASS}>
        <div className="flex justify-end">
          <Button asChild size="sm" className="h-7 text-xs">
            <Link to={describePath(position.trade_id)}>{p.describe}</Link>
          </Button>
        </div>
      </td>
    </tr>
  )
}
