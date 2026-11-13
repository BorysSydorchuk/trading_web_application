import { useMemo } from 'react'
import { formatPct } from '@/features/dashboard/format'
import { useJournalFields } from '@/features/trades/api'
import { formatR, formatSignedMoney, pnlClass, sessionLabel, weekdayLabel } from '@/features/trades/format'
import type { JournalField } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import type { Breakdown, GroupKey } from './types'

const t = uk.digests.breakdowns
const EMPTY = uk.common.empty
const TH = 'px-3 py-1.5 font-medium whitespace-nowrap'
const TD = 'px-3 py-1 whitespace-nowrap'
const NUM = `${TD} num text-right`

/** Trade fields of the snapshot; every other breakdown is a journal field with «заповнено N/M». */
const TRADE_FIELD_LABELS: Readonly<Record<string, string>> = {
  symbol: uk.trades.columns.symbol,
  session: uk.trades.columns.session,
  hour: uk.trades.columns.hour,
  weekday: uk.trades.columns.weekday,
  bias_alignment: uk.trades.columns.bias_alignment,
}

function tradeKeyLabel(field: string, key: Exclude<GroupKey, null>): string {
  if (field === 'session') return sessionLabel(String(key))
  if (field === 'weekday' && typeof key === 'number') return weekdayLabel(key)
  if (field === 'hour') return t.hour(String(key).padStart(2, '0'))
  if (field === 'bias_alignment') {
    const labels: Readonly<Record<string, string>> = uk.bias.alignment
    return Object.hasOwn(labels, String(key)) ? (labels[String(key)] ?? String(key)) : String(key)
  }
  return String(key)
}

function journalKeyLabel(field: JournalField | undefined, key: Exclude<GroupKey, null>): string {
  if (typeof key === 'boolean') return key ? uk.trades.yes : uk.trades.no
  const option = field?.options?.find((o) => o.value === String(key))
  return option?.label ?? String(key)
}

/** Breakdown tables in the snapshot order (trade fields, then analytics journal fields). */
export function BreakdownTables({ breakdowns, currency }: { breakdowns: Record<string, Breakdown>; currency: string | null }) {
  const { data } = useJournalFields()
  const fields = useMemo(() => new Map((data?.fields ?? []).map((f) => [f.key, f])), [data])
  const entries = Object.entries(breakdowns)
  return (
    <section aria-labelledby="digest-breakdowns" className="flex flex-col gap-2">
      <h2 id="digest-breakdowns" className="text-sm font-semibold">{t.title}</h2>
      <div className="grid gap-3 lg:grid-cols-2">
        {entries.map(([name, breakdown]) => (
          <BreakdownTable key={name} name={name} breakdown={breakdown} field={fields.get(name)} currency={currency} />
        ))}
      </div>
    </section>
  )
}

interface BreakdownTableProps {
  name: string
  breakdown: Breakdown
  field: JournalField | undefined
  currency: string | null
}

function BreakdownTable({ name, breakdown, field, currency }: BreakdownTableProps) {
  const isTradeField = Object.hasOwn(TRADE_FIELD_LABELS, name)
  const title = (isTradeField ? TRADE_FIELD_LABELS[name] : field?.label) ?? name
  const label = (key: GroupKey) => {
    if (key === null) return t.notFilled
    return isTradeField ? tradeKeyLabel(name, key) : journalKeyLabel(field, key)
  }
  return (
    <article aria-label={title} className="flex flex-col gap-1 rounded-lg border">
      <div className="flex items-baseline justify-between gap-2 px-3 pt-2">
        <h3 className="text-xs font-semibold">{title}</h3>
        {!isTradeField && (
          <span className="num text-xs text-muted-foreground">
            {t.coverage(breakdown.coverage.filled, breakdown.coverage.total)}
          </span>
        )}
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs text-muted-foreground">
          <tr>
            <th scope="col" className={`${TH} text-left`}>{t.key}</th>
            <th scope="col" className={`${TH} text-right`}>{t.trades}</th>
            <th scope="col" className={`${TH} text-right`}>{uk.digests.withCurrency(t.netPnl, currency)}</th>
            <th scope="col" className={`${TH} text-right`}>{t.totalR}</th>
            <th scope="col" className={`${TH} text-right`}>{t.winRate}</th>
          </tr>
        </thead>
        <tbody>
          {breakdown.groups.map((group) => (
            <tr key={String(group.key)} className="border-t">
              <td className={cn(TD, group.key === null && 'text-muted-foreground')}>{label(group.key)}</td>
              <td className={NUM}>{group.trades}</td>
              <td className={cn(NUM, pnlClass(group.net_pnl))}>{formatSignedMoney(group.net_pnl)}</td>
              <td className={NUM}>{formatR(group.total_r)}</td>
              <td className={NUM}>{group.win_rate === null ? EMPTY : formatPct(group.win_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  )
}
