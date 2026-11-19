/** Option labels for digest breakdown keys (labels from GET /api/journal-fields, raw value as fallback). */
import type { JournalField } from '@/features/trades/types'

export type FieldMap = ReadonlyMap<string, JournalField>

export function optionLabel(field: JournalField | undefined, value: string): string {
  return field?.options?.find((option) => option.value === value)?.label ?? value
}

/**
 * Distinct values in YAML option order, unknown values after them (first-seen order),
 * `null` (not filled) last.
 */
export function orderedValues(field: JournalField | undefined, values: readonly (string | null)[]): (string | null)[] {
  const present = new Set(values)
  const known = (field?.options ?? []).map((option) => option.value).filter((value) => present.has(value))
  const knownSet = new Set<string | null>(known)
  const unknown = [...present].filter((value): value is string => value !== null && !knownSet.has(value))
  return [...known, ...unknown, ...(present.has(null) ? [null] : [])]
}
