import { useState } from 'react'
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { ExcludedBadge } from '@/features/exclusion/ExcludedBadge'
import { ExclusionDialog, type ExclusionTarget } from '@/features/exclusion/ExclusionDialog'
import { TradeRowMenu } from '@/features/exclusion/TradeRowMenu'
import { TradeCell } from '@/features/trades/TradeCell'
import type { SortOrder, TradeRow, TradeSort } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { COLUMN_SORT, NUMERIC_COLUMNS, type ColumnKey } from './columns'
import { TABLE_CARD_CLASS, TABLE_HEAD_CLASS, TABLE_ROW_CLASS, TABLE_TD_CLASS, TABLE_TH_CLASS } from './tableStyles'

interface TradesTableProps {
  violationLabel: (key: string) => string
  trades: TradeRow[]
  columns: readonly ColumnKey[]
  sort: TradeSort
  order: SortOrder
  onSort: (field: TradeSort) => void
  onOpen: (trade: TradeRow) => void
  /** Dims the rows while a new page/sort loads (previous data stays visible). */
  stale?: boolean
}

export function TradesTable({ trades, columns, sort, order, onSort, onOpen, stale, violationLabel }: TradesTableProps) {
  // M8-01: one dialog for the table, opened from a row menu.
  const [exclusion, setExclusion] = useState<ExclusionTarget | null>(null)
  return (
    <div className={TABLE_CARD_CLASS}>
      <table className={cn('w-full text-[13px] transition-opacity motion-reduce:transition-none', stale && 'opacity-60')}>
        <thead className={TABLE_HEAD_CLASS}>
          <tr>
            {columns.map((key) => {
              const sortField = COLUMN_SORT[key]
              const align = NUMERIC_COLUMNS.has(key) ? 'text-right' : 'text-left'
              const label = uk.trades.columns[key]
              if (!sortField) {
                return (
                  <th key={key} scope="col" className={cn(TABLE_TH_CLASS, 'px-[5px]', align)}>
                    {label}
                  </th>
                )
              }
              const active = sort === sortField
              const Icon = active ? (order === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
              return (
                <th
                  key={key}
                  scope="col"
                  aria-sort={active ? (order === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={cn('px-0 py-1.5 font-semibold whitespace-nowrap', align)}
                >
                  <button
                    type="button"
                    onClick={() => onSort(sortField)}
                    title={uk.journal.sortBy(label)}
                    className={cn(
                      'inline-flex items-center gap-0.5 rounded-md px-[5px] py-1 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                      NUMERIC_COLUMNS.has(key) && 'flex-row-reverse',
                      active && 'text-foreground',
                    )}
                  >
                    {label}
                    <Icon className={cn('size-3', !active && 'opacity-40')} aria-hidden />
                  </button>
                </th>
              )
            })}
            <th scope="col" className="sticky right-0 bg-card px-1.5 py-2.5">
              <span className="sr-only">{uk.journal.actionsColumn}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr
              key={trade.id}
              tabIndex={0}
              aria-label={uk.journal.openRow(trade.symbol)}
              onClick={() => onOpen(trade)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onOpen(trade)
                }
              }}
              className={cn(TABLE_ROW_CLASS, 'group cursor-pointer hover:bg-accent focus-visible:bg-accent focus-visible:outline-none')}
            >
              {columns.map((key) => (
                <td
                  key={key}
                  className={cn(
                    TABLE_TD_CLASS,
                    'px-[5px] align-middle',
                    NUMERIC_COLUMNS.has(key) ? 'text-right whitespace-nowrap' : 'text-left',
                    'whitespace-nowrap',
                  )}
                >
                  <TradeCell trade={trade} column={key} violationLabel={violationLabel} />
                </td>
              ))}
              <td className="sticky right-0 bg-card px-1.5 py-1 text-right align-middle whitespace-nowrap group-hover:bg-accent group-focus-visible:bg-accent">
                <div className="flex items-center justify-end gap-1.5">
                  {trade.excluded_from_stats && <ExcludedBadge compact reason={trade.excluded_reason} />}
                  <TradeRowMenu trade={trade} onExclusion={setExclusion} />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ExclusionDialog trade={exclusion} onClose={() => setExclusion(null)} />
    </div>
  )
}
