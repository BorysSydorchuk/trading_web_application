/** Option labels for digest breakdown keys (labels from GET /api/journal-fields, raw value as fallback). */
import type { JournalField } from '@/features/trades/types'

export type FieldMap = ReadonlyMap<string, JournalField>

export function optionLabel(field: JournalField | undefined, value: string): string {
  return field?.options?.find((option) => option.value === value)?.label ?? value
}

/** Groups in the field's current option order; other keys keep their order after them. */
export function inOptionOrder<G extends { key: unknown }>(field: JournalField | undefined, groups: readonly G[]): readonly G[] {
  const rank = new Map((field?.options ?? []).map((option, index) => [option.value as unknown, index]))
  if (rank.size === 0) return groups
  return [...groups].sort((a, b) => (rank.get(a.key) ?? rank.size) - (rank.get(b.key) ?? rank.size))
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
