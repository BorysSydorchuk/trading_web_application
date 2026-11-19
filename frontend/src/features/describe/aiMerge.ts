/**
 * Puts an ExtractResult into the form without overwriting the user's own input.
 *
 * Rule: the AI may write a key only when its current value is empty or the key is still
 * marked as AI-filled (the user has not touched it since an earlier extraction). Keys the
 * user typed or changed keep the user's value. AI-filled keys that the new result does not
 * mention keep their earlier AI value and marker. An "other" text (allow_other_text) is only
 * filled when the merged value is or contains `other`. Legacy fields are never filled.
 */
import type { JournalField, JournalValue } from '@/features/trades/types'
import { RULE_VIOLATIONS_KEY, hasOther, isEditable, isEmptyValue, isLegacy, isShown, type FormValues } from './formModel'
import type { ExtractResult } from './types'

export interface MergeResult {
  values: FormValues
  aiFilled: ReadonlySet<string>
  /** Keys whose value came from this extraction. */
  applied: string[]
}

interface Fillable {
  type: string
  /** Enum key whose `other` value this text belongs to (allow_other_text only). */
  otherOf: string | null
  /** The field (or the text_key's field): a `show_if` field is filled only when it is shown. */
  field: JournalField
}

/** Every key the AI may fill; field keys come before text_keys so parents merge first. */
function fillableKeys(fields: readonly JournalField[]): Map<string, Fillable> {
  const parents = new Map<string, Fillable>()
  const texts = new Map<string, Fillable>()
  for (const field of fields) {
    if (!isEditable(field) || isLegacy(field) || field.key === RULE_VIOLATIONS_KEY) continue
    parents.set(field.key, { type: field.type, otherOf: null, field })
    if (field.text_key) texts.set(field.text_key, { type: 'text', otherOf: field.allow_other_text ? field.key : null, field })
  }
  return new Map([...parents, ...texts])
}

/** Converts an extracted value to the form representation; null when the type does not fit. */
function toFormValue(type: string, value: JournalValue): JournalValue {
  switch (type) {
    case 'int':
      return typeof value === 'number' && Number.isInteger(value) ? String(value) : null
    case 'bool':
      return typeof value === 'boolean' ? value : null
    case 'multi_enum':
      return Array.isArray(value) ? [...value] : null
    default:
      return typeof value === 'string' ? value : null
  }
}

export function mergeExtraction(
  fields: readonly JournalField[],
  values: FormValues,
  aiFilled: ReadonlySet<string>,
  result: ExtractResult,
): MergeResult {
  const nextValues: Record<string, JournalValue> = { ...values }
  const nextAi = new Set(aiFilled)
  const applied: string[] = []

  for (const [key, fillable] of fillableKeys(fields)) {
    const raw = result.fields[key]
    if (raw === undefined) continue
    if (fillable.otherOf !== null && !hasOther(nextValues[fillable.otherOf])) continue
    if (!isShown(fillable.field, nextValues)) continue
    const value = toFormValue(fillable.type, raw)
    if (isEmptyValue(value)) continue
    if (!isEmptyValue(values[key]) && !aiFilled.has(key)) continue
    nextValues[key] = value
    nextAi.add(key)
    applied.push(key)
  }
  return { values: nextValues, aiFilled: nextAi, applied }
}
