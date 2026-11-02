import { useId } from 'react'
import { MultiSelectFilter } from '@/components/MultiSelectFilter'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { useAccounts } from '@/features/accounts/api'
import { useTradeSymbols } from '@/features/trades/api'
import { statusLabel } from '@/features/trades/format'
import { TRADE_STATUSES } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { PERIOD_PRESETS, clearedFilters, hasActiveFilters, type JournalFilters, type PeriodPreset } from './filters'

const j = uk.journal

interface JournalFiltersBarProps {
  filters: JournalFilters
  onChange: (next: JournalFilters) => void
}

export function JournalFiltersBar({ filters, onChange }: JournalFiltersBarProps) {
  const id = useId()
  // Archived accounts too: their trades stay in the journal.
  const accounts = useAccounts(true)
  const symbols = useTradeSymbols()

  /** Any filter change goes back to page 1. */
  function update(patch: Partial<JournalFilters>) {
    onChange({ ...filters, ...patch, page: 1 })
  }

  const accountOptions = (accounts.data?.items ?? []).map((a) => ({ value: String(a.id), label: a.name }))
  const symbolOptions = (symbols.data?.items ?? []).map((s) => ({ value: s, label: s }))
  const statusOptions = TRADE_STATUSES.map((s) => ({ value: s, label: statusLabel(s) }))

  return (
    <div role="group" aria-label={j.filters.label} className="flex flex-wrap items-center gap-2">
      <MultiSelectFilter
        label={j.filters.account}
        options={accountOptions}
        selected={filters.accounts.map(String)}
        onChange={(values) => update({ accounts: values.map(Number) })}
      />
      <MultiSelectFilter
        label={j.filters.symbol}
        options={symbolOptions}
        selected={filters.symbols}
        onChange={(values) => update({ symbols: values })}
        mono
      />
      <MultiSelectFilter
        label={j.filters.status}
        options={statusOptions}
        selected={filters.statuses}
        onChange={(values) => update({ statuses: values })}
      />
      <label htmlFor={`${id}-period`} className="sr-only">
        {j.filters.period}
      </label>
      <div className="w-36">
        <NativeSelect
          id={`${id}-period`}
          className="h-8 text-xs"
          value={filters.period}
          onChange={(e) => update({ period: e.target.value as PeriodPreset })}
        >
          {PERIOD_PRESETS.map((p) => (
            <option key={p} value={p}>
              {j.periods[p]}
            </option>
          ))}
        </NativeSelect>
      </div>
      {filters.period === 'custom' && (
        <>
          <label htmlFor={`${id}-from`} className="text-xs text-muted-foreground">
            {j.filters.from}
          </label>
          <Input
            id={`${id}-from`}
            type="date"
            className="num h-8 w-36 text-xs"
            value={filters.from}
            max={filters.to || undefined}
            onChange={(e) => update({ from: e.target.value })}
          />
          <label htmlFor={`${id}-to`} className="text-xs text-muted-foreground">
            {j.filters.to}
          </label>
          <Input
            id={`${id}-to`}
            type="date"
            className="num h-8 w-36 text-xs"
            value={filters.to}
            min={filters.from || undefined}
            onChange={(e) => update({ to: e.target.value })}
          />
        </>
      )}
      {hasActiveFilters(filters) && (
        <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={() => onChange(clearedFilters(filters))}>
          {j.resetFilters}
        </Button>
      )}
    </div>
  )
}
