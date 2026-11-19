/** M8-04..08: filters by journal field values (POI, FVG types, H1/H4 context, entry model). */
import { useMemo } from 'react'
import { MultiSelectFilter, type FilterOption } from '@/components/MultiSelectFilter'
import type { JournalField } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { JOURNAL_FILTER_KEYS, JOURNAL_NULL_VALUE, withJournalFilter, type JournalFieldFilters as Selection } from './filters'

interface JournalFieldFiltersProps {
  /** Field definitions loaded by the page (one subscription per page). */
  fields: readonly JournalField[] | undefined
  selection: Selection
  onChange: (next: Selection) => void
}

function filterOptions(field: JournalField): FilterOption[] {
  // Deprecated options stay filterable: old trades keep those values.
  const options = (field.options ?? []).map((option) => ({ value: option.value, label: option.label }))
  return [...options, { value: JOURNAL_NULL_VALUE, label: uk.journal.filters.notFilled }]
}

/**
 * One multi-select per filterable field the API defines (labels and options from
 * GET /api/journal-fields). Without the field list nothing is shown; URL filters still apply.
 */
export function JournalFieldFilters({ fields, selection, onChange }: JournalFieldFiltersProps) {
  const filterable = useMemo(() => {
    const byKey = new Map((fields ?? []).map((field) => [field.key, field]))
    return JOURNAL_FILTER_KEYS.map((key) => byKey.get(key)).filter(
      (field): field is JournalField => field !== undefined && field.legacy !== true,
    )
  }, [fields])

  return (
    <>
      {filterable.map((field) => (
        <MultiSelectFilter
          key={field.key}
          label={field.label}
          options={filterOptions(field)}
          selected={selection[field.key] ?? []}
          onChange={(values) => onChange(withJournalFilter(selection, field.key, values))}
        />
      ))}
    </>
  )
}
