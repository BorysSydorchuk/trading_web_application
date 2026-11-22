import { formatPct } from '@/features/dashboard/format'
import { formatR, formatSignedMoney } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { decimalSign } from '@/lib/decimal'
import { cn } from '@/lib/utils'
import { BLOCK_TITLE } from './tableStyles'
import type { Breakdown, GroupKey } from './types'

const t = uk.digests.breakdowns
const EMPTY = uk.common.empty
const PROFIT_SCALE = ['bg-profit-wash', 'bg-profit-soft', 'bg-profit-light'] as const
const LOSS_SCALE = ['bg-loss-wash', 'bg-loss-soft', 'bg-loss-light'] as const

/** Pastel step by the size of the P&L against the largest one in this card (colour only). */
function pnlCellClass(netPnl: string, maxAbs: number): string {
  const sign = decimalSign(netPnl)
  if (sign === 0 || maxAbs === 0) return 'bg-track'
  const step = Math.min(2, Math.floor((Math.abs(Number(netPnl)) / maxAbs) * 3))
  return (sign > 0 ? PROFIT_SCALE : LOSS_SCALE)[step] ?? 'bg-track'
}

interface TimeBreakdownCardProps {
  title: string
  breakdown: Breakdown
  label: (key: GroupKey) => string
  currency: string | null
}

/** «Дні» / «Години»: one pastel cell per group with P&L, trades, R and win rate. */
export function TimeBreakdownCard({ title, breakdown, label, currency }: TimeBreakdownCardProps) {
  const maxAbs = Math.max(0, ...breakdown.groups.map((group) => Math.abs(Number(group.net_pnl))))
  return (
    <article aria-label={title} className="flex flex-col gap-3 rounded-card border border-line bg-card p-4 lg:col-span-2">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className={BLOCK_TITLE}>{title}</h3>
        <span className="text-xs text-ink-muted">{uk.digests.withCurrency(t.netPnl, currency)}</span>
      </div>
      <ul className="m-0 grid list-none grid-cols-[repeat(auto-fit,minmax(5.75rem,1fr))] gap-2 p-0">
        {breakdown.groups.map((group) => (
          <li key={String(group.key)} className={cn('flex flex-col gap-0.5 rounded-lg px-2.5 py-2 text-ink', pnlCellClass(group.net_pnl, maxAbs))}>
            <span className="text-xs font-semibold">{label(group.key)}</span>
            <span className="num text-sm font-bold">{formatSignedMoney(group.net_pnl)}</span>
            <span className="num text-[11px]">{t.cellTrades(group.trades)}</span>
            <span className="num text-[11px]">{formatR(group.total_r)}</span>
            <span className="num text-[11px]">{group.win_rate === null ? EMPTY : t.cellWinRate(formatPct(group.win_rate))}</span>
          </li>
        ))}
      </ul>
    </article>
  )
}
