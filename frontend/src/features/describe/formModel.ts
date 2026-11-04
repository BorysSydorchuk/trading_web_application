/**
 * Journal form model, generated from GET /api/journal-fields (no field list in code).
 * Pure functions only: values in, new values out (no mutation).
 */
import type { JournalField, JournalFieldOption, JournalValue } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { hasBeforeLink, type LinkDraft } from './chartLinks'

/** Form values keyed by YAML key (fields and text_keys). Ints are kept as digit strings while editing. */
export type FormValues = Readonly<Record<string, JournalValue>>

export const MAX_TEXT_LENGTH = 5000
export const MAX_RAW_TEXT_LENGTH = 20000
export const OTHER_OPTION = 'other'
export const RULE_VIOLATIONS_KEY = 'rule_violations'

/** DOM id of a field's control (focus the first missing field, label `for`). */
export function fieldDomId(key: string): string {
  return `describe-field-${key}`
}

/** Types the AI may fill (aiMerge); `auto` is read-only, `links` has its own editor. */
const EDITABLE_TYPES = new Set(['enum', 'multi_enum', 'bool', 'int', 'text'])

export function isEditable(field: JournalField): boolean {
  return EDITABLE_TYPES.has(field.type)
}

/** Field types never sent in the PUT `fields` (docs/api.md): everything else is, incl. unknown types. */
const NOT_SENT_TYPES = new Set(['auto', 'links'])

function isSent(field: JournalField): boolean {
  return !NOT_SENT_TYPES.has(field.type)
}

/**
 * Fields as they apply to this trade: keys in `TradeDetail.missing_new_fields` became required
 * after the trade closed, so they are not required here (no red mark, no block on `complete`;
 * the server's missing_required already leaves them out). Returns new objects, input unchanged.
 */
export function fieldsForTrade(fields: readonly JournalField[], newFields: readonly string[]): readonly JournalField[] {
  if (newFields.length === 0) return fields
  const exempt = new Set(newFields)
  return fields.map((field) => (exempt.has(field.key) && field.required ? { ...field, required: false } : field))
}

/** Fields rendered in the form (everything except links, which have their own editor). */
export function formFields(fields: readonly JournalField[]): JournalField[] {
  return fields.filter((field) => field.type !== 'links')
}

export function linksField(fields: readonly JournalField[]): JournalField | undefined {
  return fields.find((field) => field.type === 'links')
}

function toFormValue(field: JournalField, value: JournalValue | undefined): JournalValue {
  if (value === undefined || value === null) return field.type === 'multi_enum' ? [] : null
  if (field.type === 'int' && typeof value === 'number') return String(value)
  if (Array.isArray(value)) return [...value]
  return value
}

/** Initial values from TradeDetail.journal: every field key plus its text_key. */
export function initialValues(
  fields: readonly JournalField[],
  journal: Readonly<Record<string, JournalValue>>,
): FormValues {
  const values: Record<string, JournalValue> = {}
  for (const field of formFields(fields)) {
    values[field.key] = toFormValue(field, journal[field.key])
    if (field.text_key) values[field.text_key] = journal[field.text_key] ?? null
  }
  return values
}

export function isEmptyValue(value: JournalValue | undefined): boolean {
  if (value === undefined || value === null) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

/** text_key that only applies to the `other` option and is hidden otherwise. */
export function otherTextActive(field: JournalField, values: FormValues): boolean {
  return field.allow_other_text === true && values[field.key] === OTHER_OPTION
}

/**
 * Keys that block `complete`, in YAML order (same rule as the server, docs/api.md):
 * required fields must be filled, an `other` text when its enum is `other`, a `before` chart link.
 */
export function missingKeys(
  fields: readonly JournalField[],
  values: FormValues,
  links: readonly LinkDraft[],
): string[] {
  const missing: string[] = []
  for (const field of fields) {
    if (field.type === 'links') {
      if (field.required && !hasBeforeLink(links)) missing.push(field.key)
      continue
    }
    if (field.required && isEmptyValue(values[field.key])) missing.push(field.key)
    if (field.text_key && otherTextActive(field, values) && isEmptyValue(values[field.text_key])) {
      missing.push(field.text_key)
    }
  }
  return missing
}

function trimmedOrNull(value: JournalValue | undefined): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function fieldPayload(field: JournalField, value: JournalValue | undefined): JournalValue {
  switch (field.type) {
    case 'enum':
      return typeof value === 'string' && value !== '' ? value : null
    case 'multi_enum':
      return Array.isArray(value) && value.length > 0 ? [...value] : null
    case 'bool':
      return typeof value === 'boolean' ? value : null
    case 'int': {
      const text = trimmedOrNull(value)
      return text !== null && /^-?\d+$/.test(text) ? Number(text) : null
    }
    case 'text':
      return trimmedOrNull(value)
    default:
      return value ?? null
  }
}

/**
 * `fields` of the PUT body: every YAML key except auto and links. A type this UI does not know
 * is sent back unchanged (a key missing from the body would be cleared by the server).
 */
export function buildFields(fields: readonly JournalField[], values: FormValues): Record<string, JournalValue> {
  const payload: Record<string, JournalValue> = {}
  for (const field of fields) {
    if (!isSent(field)) continue
    payload[field.key] = fieldPayload(field, values[field.key])
    if (!field.text_key) continue
    const textApplies = !field.allow_other_text || otherTextActive(field, values)
    payload[field.text_key] = textApplies ? trimmedOrNull(values[field.text_key]) : null
  }
  return payload
}

/** Keys that have a visible control right now (a server error on any other key goes to the general message). */
export function renderedKeys(fields: readonly JournalField[], values: FormValues): Set<string> {
  const keys = new Set<string>()
  for (const field of formFields(fields)) {
    keys.add(field.key)
    if (field.text_key && (!field.allow_other_text || otherTextActive(field, values))) keys.add(field.text_key)
  }
  return keys
}

/** ai_filled_fields for the PUT body: only keys that are still sent with a value. */
export function aiFilledForSave(
  aiFilled: ReadonlySet<string>,
  payload: Readonly<Record<string, JournalValue>>,
): string[] {
  return [...aiFilled].filter((key) => payload[key] !== null && payload[key] !== undefined)
}

/** Options to show: active ones, plus deprecated/unknown values the trade already stores. */
export function visibleOptions(field: JournalField, stored: JournalValue | undefined): JournalFieldOption[] {
  const storedValues = new Set(Array.isArray(stored) ? stored : typeof stored === 'string' ? [stored] : [])
  const all = field.options ?? []
  const options = all.filter((option) => !option.deprecated || storedValues.has(option.value))
  const defined = new Set(all.map((option) => option.value))
  // A stored value missing from the YAML is shown raw, so saving does not silently drop it.
  const unknown = [...storedValues]
    .filter((value) => !defined.has(value))
    .map((value) => ({ value, label: value, deprecated: true }))
  return [...options, ...unknown]
}

/** Label for any YAML key (field or text_key), used by "Не вистачає: …". */
export function keyLabels(fields: readonly JournalField[]): Map<string, string> {
  const labels = new Map<string, string>()
  for (const field of fields) {
    labels.set(field.key, field.label)
    if (field.text_key) {
      const suffix = field.allow_other_text ? uk.describe.form.otherTextSuffix : uk.describe.form.noteSuffix
      labels.set(field.text_key, `${field.label} ${suffix}`)
    }
  }
  return labels
}

/** Client error for an int field typed in a number input (segmented ints cannot be invalid). */
export function intError(field: JournalField, value: JournalValue | undefined): string | null {
  const text = trimmedOrNull(value)
  if (text === null) return null
  if (!/^-?\d+$/.test(text)) return uk.describe.form.intInvalid
  const n = Number(text)
  if ((field.min !== undefined && n < field.min) || (field.max !== undefined && n > field.max)) {
    return uk.describe.form.intRange(field.min ?? null, field.max ?? null)
  }
  return null
}

export function intFieldErrors(fields: readonly JournalField[], values: FormValues): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const field of fields) {
    if (field.type !== 'int') continue
    const error = intError(field, values[field.key])
    if (error) errors[field.key] = error
  }
  return errors
}
