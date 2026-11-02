import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { TradeCell } from '@/features/trades/TradeCell'
import type { SortOrder, TradeRow, TradeSort } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { COLUMN_SORT, NUMERIC_COLUMNS, type ColumnKey } from './columns'

interface TradesTableProps {
  trades: TradeRow[]
  columns: readonly ColumnKey[]
  sort: TradeSort
  order: SortOrder
  onSort: (field: TradeSort) => void
  onOpen: (trade: TradeRow) => void
  /** Dims the rows while a new page/sort loads (previous data stays visible). */
  stale?: boolean
}

export function TradesTable({ trades, columns, sort, order, onSort, onOpen, stale }: TradesTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className={cn('w-full text-sm transition-opacity', stale && 'opacity-60')}>
        <thead className="bg-muted/40 text-xs text-muted-foreground">
          <tr>
            {columns.map((key) => {
              const sortField = COLUMN_SORT[key]
              const align = NUMERIC_COLUMNS.has(key) ? 'text-right' : 'text-left'
              const label = uk.trades.columns[key]
              if (!sortField) {
                return (
                  <th key={key} scope="col" className={cn('px-3 py-2 font-medium whitespace-nowrap', align)}>
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
                  className={cn('px-1 py-1 font-medium whitespace-nowrap', align)}
                >
                  <button
                    type="button"
                    onClick={() => onSort(sortField)}
                    title={uk.journal.sortBy(label)}
                    className={cn(
                      'inline-flex items-center gap-1 rounded px-2 py-1 hover:bg-accent/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none',
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
              className="cursor-pointer border-t hover:bg-muted/30 focus-visible:bg-muted/40 focus-visible:outline-none"
            >
              {columns.map((key) => (
                <td
                  key={key}
                  className={cn(
                    'px-3 py-1.5 align-top',
                    NUMERIC_COLUMNS.has(key) ? 'text-right whitespace-nowrap' : 'text-left',
                    key !== 'violations' && 'whitespace-nowrap',
                  )}
                >
                  <TradeCell trade={trade} column={key} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
