/**
 * Journal form generated from GET /api/journal-fields: enum → buttons/select, multi_enum →
 * checkboxes, bool → так/ні, int → number (buttons for a short range), text → textarea,
 * auto → read-only. A field added to config/journal_fields.yaml appears without code changes.
 */
import { Eraser, Lock } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { NativeSelect } from '@/components/ui/native-select'
import { Textarea } from '@/components/ui/textarea'
import type { JournalField, JournalValue } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { FieldShell, Segmented } from './FieldControls'
import type { Mt5FillSource } from './mt5Prefill'
import {
  fieldDomId,
  MAX_TEXT_LENGTH,
  RULE_VIOLATIONS_KEY,
  formFields,
  isEmptyValue,
  isLegacy,
  isShown,
  otherTextActive,
  toBeCleared,
  visibleOptions,
  type FormValues,
} from './formModel'

const f = uk.describe.form
/** Up to this many options an enum is a row of buttons, above it a select. */
const SEGMENTED_MAX_OPTIONS = 4
/** Int fields with a range up to this size are buttons (e.g. quality 1–5). */
const SEGMENTED_MAX_INT_RANGE = 10

export interface JournalFormProps {
  fields: readonly JournalField[]
  values: FormValues
  /** Values stored on the trade (deprecated options stay selectable only for these). */
  stored: FormValues
  journal: Readonly<Record<string, JournalValue>>
  aiFilled: ReadonlySet<string>
  /** M8-09: fields prefilled from MT5 (exit_reason). */
  mt5Filled?: ReadonlyMap<string, Mt5FillSource>
  missing: ReadonlySet<string>
  errors: Readonly<Record<string, string>>
  autoViolations: ReadonlySet<string>
  onChange: (key: string, value: JournalValue) => void
}

export function JournalForm(props: JournalFormProps) {
  const shownFields = formFields(props.fields)
  // show_if children that are hidden now but still hold a value, by parent key («Буде очищено»).
  const cleared = new Map<string, string[]>()
  for (const child of toBeCleared(shownFields, props.values)) {
    const parent = child.show_if?.field ?? ''
    cleared.set(parent, [...(cleared.get(parent) ?? []), child.label])
  }
  return (
    <div className="flex flex-col gap-2">
      {shownFields.map((field) => (
        <FieldEntry key={field.key} field={field} cleared={cleared.get(field.key)} {...props} />
      ))}
    </div>
  )
}

type FieldProps = JournalFormProps & { field: JournalField }

/** One YAML field: hidden by show_if → nothing; legacy → read-only old value; else the control. */
function FieldEntry({ cleared, ...props }: FieldProps & { cleared: string[] | undefined }) {
  const { field, values, journal } = props
  if (isLegacy(field)) return isEmptyValue(journal[field.key]) ? null : <LegacyBlock field={field} journal={journal} />
  if (!isShown(field, values)) return null
  return (
    <>
      <FieldBlock {...props} />
      {cleared && <ClearNote labels={cleared} />}
    </>
  )
}

/** Inline warning under a parent: these hidden fields lose their values on save. */
function ClearNote({ labels }: { labels: readonly string[] }) {
  return (
    <div role="note" className="ml-3 flex gap-2 rounded-md border border-dashed px-3 py-1.5 text-xs text-muted-foreground">
      <Eraser className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <div className="flex flex-col gap-0.5">
        <p className="text-foreground">{f.willBeCleared(labels.join(', '))}</p>
        <p>{f.willBeClearedHint}</p>
      </div>
    </div>
  )
}

function optionLabel(field: JournalField, value: string): string {
  return field.options?.find((option) => option.value === value)?.label ?? value
}

/** M8-04..08: an old field the new taxonomy replaced; never editable, never sent. */
function LegacyBlock({ field, journal }: Pick<FieldProps, 'field' | 'journal'>) {
  const value = journal[field.key]
  const label = Array.isArray(value)
    ? value.map((v) => optionLabel(field, v)).join(', ')
    : optionLabel(field, String(value))
  return (
    <div className="flex flex-col gap-0.5 border-l-2 border-transparent py-1 pl-3" title={f.legacyHint}>
      <span className="text-xs font-medium text-muted-foreground">{field.label}</span>
      <p id={fieldDomId(field.key)} className="text-xs text-muted-foreground">
        {f.legacyValue(label)}
      </p>
    </div>
  )
}

function FieldBlock(props: FieldProps) {
  const { field, values, stored, aiFilled, mt5Filled, missing, errors } = props
  const group = field.type !== 'text' && field.type !== 'int' && !(field.type === 'enum' && enumUsesSelect(field, stored))
  return (
    <>
      <FieldShell
        fieldKey={field.key}
        label={field.label}
        required={field.required === true}
        aiFilled={aiFilled.has(field.key)}
        mt5Fill={mt5Filled?.get(field.key) ?? null}
        missing={missing.has(field.key)}
        error={errors[field.key] ?? null}
        hint={field.type === 'auto' ? f.autoHint : undefined}
        group={group}
      >
        <FieldInput {...props} />
      </FieldShell>
      {field.text_key && (!field.allow_other_text || otherTextActive(field, values)) && (
        <TextKeyBlock {...props} textKey={field.text_key} />
      )}
    </>
  )
}

function enumUsesSelect(field: JournalField, stored: FormValues): boolean {
  return visibleOptions(field, stored[field.key]).length > SEGMENTED_MAX_OPTIONS
}

function asList(value: JournalValue | undefined): string[] {
  return Array.isArray(value) ? value : []
}

function FieldInput(props: FieldProps) {
  switch (props.field.type) {
    case 'enum':
      return <EnumInput {...props} />
    case 'multi_enum':
      return <MultiEnumInput {...props} />
    case 'bool':
      return <BoolInput {...props} />
    case 'int':
      return <IntInput {...props} />
    case 'text':
      return <TextInput {...props} />
    case 'auto':
      return <AutoValue {...props} />
    default:
      return <RawValue {...props} />
  }
}

function EnumInput({ field, values, stored, missing, onChange }: FieldProps) {
  const value = values[field.key]
  const current = typeof value === 'string' ? value : null
  const options = visibleOptions(field, stored[field.key])
  const invalid = missing.has(field.key)
  if (enumUsesSelect(field, stored)) {
    return (
      <NativeSelect
        id={fieldDomId(field.key)}
        className="h-7 text-xs"
        wrapperClassName="max-w-xs"
        value={current ?? ''}
        aria-invalid={invalid || undefined}
        onChange={(e) => onChange(field.key, e.target.value === '' ? null : e.target.value)}
      >
        <option value="">{f.notSelected}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.deprecated ? f.deprecatedOption(option.label) : option.label}
          </option>
        ))}
      </NativeSelect>
    )
  }
  return (
    <Segmented
      id={fieldDomId(field.key)}
      options={options.map((o) => ({ value: o.value, label: o.deprecated ? f.deprecatedOption(o.label) : o.label }))}
      value={current}
      invalid={invalid}
      onChange={(next) => onChange(field.key, next)}
    />
  )
}

function MultiEnumInput({ field, values, stored, autoViolations, onChange }: FieldProps) {
  const selected = asList(values[field.key])
  const isRules = field.key === RULE_VIOLATIONS_KEY
  // Auto violations are always listed (locked), even if a rule key is missing from the YAML.
  const options = visibleOptions(field, isRules ? [...asList(stored[field.key]), ...autoViolations] : stored[field.key])

  function toggle(value: string, checked: boolean) {
    const next = checked ? [...selected, value] : selected.filter((v) => v !== value)
    onChange(field.key, next)
  }

  return (
    <div id={fieldDomId(field.key)} className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
      {options.map((option) => {
        const locked = isRules && autoViolations.has(option.value)
        const checked = locked || selected.includes(option.value)
        return (
          <label
            key={option.value}
            className={cn('flex items-center gap-2 text-xs', locked ? 'cursor-default' : 'cursor-pointer')}
            title={locked ? f.autoViolationHint : undefined}
          >
            <input
              type="checkbox"
              className="size-3.5 accent-primary"
              checked={checked}
              disabled={locked}
              onChange={(e) => toggle(option.value, e.target.checked)}
            />
            <span className={cn(locked && 'text-loss')}>{option.label}</span>
            {locked && (
              <span className="inline-flex items-center gap-0.5 text-[10px] text-muted-foreground">
                <Lock className="size-2.5" aria-hidden />
                {uk.trades.violationSource.auto}
              </span>
            )}
          </label>
        )
      })}
    </div>
  )
}

function BoolInput({ field, values, missing, onChange }: FieldProps) {
  const value = values[field.key]
  const current = value === true ? 'true' : value === false ? 'false' : null
  return (
    <Segmented
      id={fieldDomId(field.key)}
      options={[
        { value: 'true', label: uk.trades.yes },
        { value: 'false', label: uk.trades.no },
      ]}
      value={current}
      invalid={missing.has(field.key)}
      onChange={(next) => onChange(field.key, next === null ? null : next === 'true')}
    />
  )
}

function intRange(field: JournalField): number[] | null {
  if (field.min === undefined || field.max === undefined) return null
  const size = field.max - field.min + 1
  if (size < 1 || size > SEGMENTED_MAX_INT_RANGE) return null
  return Array.from({ length: size }, (_, i) => (field.min ?? 0) + i)
}

function IntInput({ field, values, missing, errors, onChange }: FieldProps) {
  const value = values[field.key]
  const text = typeof value === 'string' ? value : ''
  const range = intRange(field)
  const invalid = missing.has(field.key) || errors[field.key] !== undefined
  if (range) {
    return (
      <Segmented
        id={fieldDomId(field.key)}
        mono
        options={range.map((n) => ({ value: String(n), label: String(n) }))}
        value={text === '' ? null : text}
        invalid={invalid}
        onChange={(next) => onChange(field.key, next)}
      />
    )
  }
  return (
    <Input
      id={fieldDomId(field.key)}
      type="number"
      inputMode="numeric"
      step={1}
      min={field.min}
      max={field.max}
      className="num h-7 w-28 text-right text-xs"
      value={text}
      aria-invalid={invalid || undefined}
      onChange={(e) => onChange(field.key, e.target.value === '' ? null : e.target.value)}
    />
  )
}

function TextInput({ field, values, missing, errors, onChange }: FieldProps) {
  const value = values[field.key]
  return (
    <Textarea
      id={fieldDomId(field.key)}
      rows={2}
      maxLength={MAX_TEXT_LENGTH}
      className="text-xs"
      value={typeof value === 'string' ? value : ''}
      aria-invalid={missing.has(field.key) || errors[field.key] !== undefined || undefined}
      onChange={(e) => onChange(field.key, e.target.value === '' ? null : e.target.value)}
    />
  )
}

function AutoValue({ field, journal }: FieldProps) {
  const value = journal[field.key]
  const label = field.options?.find((o) => o.value === value)?.label ?? (typeof value === 'string' ? value : null)
  return (
    <p id={fieldDomId(field.key)} className="text-xs">
      {label ?? <span className="text-muted-foreground">{f.autoEmpty}</span>}
    </p>
  )
}

/** A field type this UI does not know yet: shown read-only and sent back unchanged. */
function RawValue({ field, values }: FieldProps) {
  const value = values[field.key]
  return (
    <p id={fieldDomId(field.key)} className="num text-xs text-muted-foreground">
      {value === null || value === undefined ? uk.common.empty : JSON.stringify(value)}
    </p>
  )
}

function TextKeyBlock({ field, textKey, values, aiFilled, missing, errors, onChange }: FieldProps & { textKey: string }) {
  const value = values[textKey]
  const isOther = field.allow_other_text === true
  return (
    <FieldShell
      fieldKey={textKey}
      label={isOther ? f.otherTextLabel : f.noteLabel(field.label)}
      required={isOther && field.other_text_optional !== true}
      aiFilled={aiFilled.has(textKey)}
      missing={missing.has(textKey)}
      error={errors[textKey] ?? null}
    >
      <Input
        id={fieldDomId(textKey)}
        maxLength={MAX_TEXT_LENGTH}
        className="h-7 text-xs"
        value={typeof value === 'string' ? value : ''}
        aria-invalid={missing.has(textKey) || errors[textKey] !== undefined || undefined}
        onChange={(e) => onChange(textKey, e.target.value === '' ? null : e.target.value)}
      />
    </FieldShell>
  )
}
