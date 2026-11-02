import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useSearchParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { ColumnChooser } from '@/features/journal/ColumnChooser'
import { loadColumns, saveColumns, type ColumnKey } from '@/features/journal/columns'
import {
  clearedFilters,
  filtersToParams,
  hasActiveFilters,
  parseFilters,
  toTradeQuery,
  type JournalFilters,
} from '@/features/journal/filters'
import { JournalFiltersBar } from '@/features/journal/JournalFiltersBar'
import { Pagination } from '@/features/journal/Pagination'
import { TradesTable } from '@/features/journal/TradesTable'
import { useTrades } from '@/features/trades/api'
import { TradeDetailDialog } from '@/features/trades/TradeDetailDialog'
import type { TradeSort } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { brusselsToday } from '@/lib/time'

const j = uk.journal

export function JournalPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filters = useMemo(() => parseFilters(searchParams), [searchParams])
  // Presets (today, this week…) depend on the Brussels date, so a new day gives a new query.
  const today = brusselsToday()
  const query = useMemo(() => toTradeQuery({ ...filters, trade: null }, today), [filters, today])
  const { data, isPending, isError, error, refetch, isFetching, isPlaceholderData } = useTrades(query)

  const [columns, setColumns] = useState<ColumnKey[]>(loadColumns)

  function setFilters(next: JournalFilters) {
    setSearchParams(filtersToParams(next), { replace: true })
  }

  function changeColumns(next: ColumnKey[]) {
    setColumns(next)
    saveColumns(next)
  }

  function sortBy(field: TradeSort) {
    const order = filters.sort === field && filters.order === 'desc' ? 'asc' : 'desc'
    setFilters({ ...filters, sort: field, order, page: 1 })
  }

  let body
  if (isPending) {
    body = (
      <div className="flex flex-col gap-2" role="status" aria-label={j.loading}>
        {[0, 1, 2, 3, 4].map((row) => (
          <div key={row} className="h-8 animate-pulse rounded-md bg-muted/50" />
        ))}
        <span className="sr-only">{j.loading}</span>
      </div>
    )
  } else if (isError) {
    body = (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p>{j.loadError}</p>
        <p className="text-xs text-muted-foreground">{errorText(error)}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching && <Loader2 className="animate-spin" aria-hidden />}
          {uk.common.retry}
        </Button>
      </div>
    )
  } else if (data.items.length === 0 && data.total > 0) {
    // Page past the end (e.g. trades were removed since the link was made).
    body = (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p className="text-muted-foreground">{j.empty}</p>
        <Button variant="outline" size="sm" onClick={() => setFilters({ ...filters, page: 1 })}>
          {j.firstPage}
        </Button>
      </div>
    )
  } else if (data.items.length === 0) {
    const filtered = hasActiveFilters(filters)
    body = (
      <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
        <p className="text-muted-foreground">{filtered ? j.empty : j.emptyNoFilters}</p>
        {filtered && (
          <Button variant="outline" size="sm" onClick={() => setFilters(clearedFilters(filters))}>
            {j.resetFilters}
          </Button>
        )}
      </div>
    )
  } else {
    body = (
      <>
        <TradesTable
          trades={data.items}
          columns={columns}
          sort={filters.sort}
          order={filters.order}
          onSort={sortBy}
          onOpen={(trade) => setFilters({ ...filters, trade: trade.id })}
          stale={isPlaceholderData}
        />
        <Pagination
          page={filters.page}
          limit={filters.limit}
          total={data.total}
          onPage={(page) => setFilters({ ...filters, page })}
          onLimit={(limit) => setFilters({ ...filters, limit, page: 1 })}
        />
      </>
    )
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold tracking-tight">{uk.pages.journal.title}</h1>
        {data && (
          <span className="num text-xs text-muted-foreground">{j.total(data.total)}</span>
        )}
        {isFetching && !isPending && (
          <Loader2 className="size-4 animate-spin text-muted-foreground" aria-hidden />
        )}
        <div className="ml-auto">
          <ColumnChooser visible={columns} onChange={changeColumns} />
        </div>
      </div>
      <JournalFiltersBar filters={filters} onChange={setFilters} />
      {body}
      <TradeDetailDialog tradeId={filters.trade} onClose={() => setFilters({ ...filters, trade: null })} />
    </section>
  )
}
