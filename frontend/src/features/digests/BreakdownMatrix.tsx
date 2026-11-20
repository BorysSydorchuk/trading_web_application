/**
 * M8-04..08 `matrix` breakdown (`h1_context__x__h4_context`): rows = the first field's values,
 * columns = the second's, each cell «N угод · P&L · R · WR», an empty cell «—».
 */
import { formatPct } from '@/features/dashboard/format'
import { formatR, formatSignedMoney, pnlClass } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { optionLabel, orderedValues, type FieldMap } from './breakdownLabels'
import { BLOCK_TITLE, ROW, THEAD, TITLED_TABLE_CARD } from './tableStyles'
import type { Breakdown, BreakdownGroup } from './types'

const t = uk.digests.breakdowns
const MATRIX_SEPARATOR = '__x__'
const CELL = 'px-3 py-1.5 whitespace-nowrap'

interface BreakdownMatrixProps {
  name: string
  breakdown: Breakdown
  fields: FieldMap
  currency: string | null
}

type Part = string | null

function pair(group: BreakdownGroup): [Part, Part] {
  const key = group.key
  if (!Array.isArray(key)) return [null, null]
  const [row = null, column = null] = key as readonly Part[]
  return [row, column]
}

function cellId(row: Part, column: Part): string {
  return JSON.stringify([row, column])
}

export function BreakdownMatrix({ name, breakdown, fields, currency }: BreakdownMatrixProps) {
  const [rowKey = name, columnKey = ''] = name.split(MATRIX_SEPARATOR)
  const rowField = fields.get(rowKey)
  const columnField = fields.get(columnKey)
  const rowTitle = rowField?.label ?? rowKey
  const columnTitle = columnField?.label ?? columnKey
  const title = t.matrixTitle(rowTitle, columnTitle)

  const pairs = breakdown.groups.map((group) => ({ group, key: pair(group) }))
  const rows = orderedValues(rowField, pairs.map((p) => p.key[0]))
  const columns = orderedValues(columnField, pairs.map((p) => p.key[1]))
  const cells = new Map(pairs.map((p) => [cellId(p.key[0], p.key[1]), p.group]))
  const valueLabel = (field: typeof rowField, value: Part) => (value === null ? t.notFilled : optionLabel(field, value))

  return (
    <article aria-label={title} className={cn(TITLED_TABLE_CARD, 'lg:col-span-2')}>
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-1">
        <h3 className={BLOCK_TITLE}>{title}</h3>
        <span className="num text-xs text-ink-muted">
          {t.coverage(breakdown.coverage.filled, breakdown.coverage.total)}
        </span>
      </div>
      <p className="px-4 text-[11px] text-ink-muted">
        {uk.digests.withCurrency(t.matrixLegend, currency)}
      </p>
      <div className="overflow-x-auto px-1">
        <table className="w-full text-xs">
          <thead className={THEAD}>
            <tr>
              <th scope="col" className={`${CELL} text-left font-medium`}>
                {t.matrixCorner(rowTitle, columnTitle)}
              </th>
              {columns.map((column) => (
                <th key={String(column)} scope="col" className={`${CELL} text-right font-medium`}>
                  {valueLabel(columnField, column)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row)} className={ROW}>
                <th scope="row" className={cn(CELL, 'text-left font-normal', row === null && 'text-ink-muted')}>
                  {valueLabel(rowField, row)}
                </th>
                {columns.map((column) => (
                  <td key={String(column)} className={`${CELL} num text-right`}>
                    <MatrixCell group={cells.get(cellId(row, column))} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  )
}

function MatrixCell({ group }: { group: BreakdownGroup | undefined }) {
  if (!group || group.trades === 0) return <span className="text-ink-muted">{t.matrixEmpty}</span>
  return (
    <span>
      {t.matrixTrades(group.trades)}
      {' · '}
      <span className={pnlClass(group.net_pnl)}>{formatSignedMoney(group.net_pnl)}</span>
      {' · '}
      {formatR(group.total_r)}
      {' · '}
      {group.win_rate === null ? uk.common.empty : formatPct(group.win_rate)}
    </span>
  )
}
