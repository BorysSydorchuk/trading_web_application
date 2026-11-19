/**
 * M8-04..08 `matrix` breakdown (`h1_context__x__h4_context`): rows = the first field's values,
 * columns = the second's, each cell «N угод · P&L · R · WR», an empty cell «—».
 */
import { formatPct } from '@/features/dashboard/format'
import { formatR, formatSignedMoney, pnlClass } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { optionLabel, orderedValues, type FieldMap } from './breakdownLabels'
import type { Breakdown, BreakdownGroup } from './types'

const t = uk.digests.breakdowns
const MATRIX_SEPARATOR = '__x__'
const CELL = 'px-2 py-1 whitespace-nowrap'

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
    <article aria-label={title} className="flex flex-col gap-1 rounded-lg border lg:col-span-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-3 pt-2">
        <h3 className="text-xs font-semibold">{title}</h3>
        <span className="num text-xs text-muted-foreground">
          {t.coverage(breakdown.coverage.filled, breakdown.coverage.total)}
        </span>
      </div>
      <p className="px-3 text-[11px] text-muted-foreground">
        {uk.digests.withCurrency(t.matrixLegend, currency)}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground">
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
              <tr key={String(row)} className="border-t">
                <th scope="row" className={cn(CELL, 'text-left font-normal', row === null && 'text-muted-foreground')}>
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
  if (!group || group.trades === 0) return <span className="text-muted-foreground">{t.matrixEmpty}</span>
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
