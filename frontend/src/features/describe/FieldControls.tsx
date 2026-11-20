/** Small building blocks of the journal form. */
import type { ReactNode } from 'react'
import { Sparkles } from 'lucide-react'
import type { Mt5FillSource } from './mt5Prefill'
import { selectedToggleClass } from '@/components/studio/tones'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { fieldDomId } from './formModel'

const f = uk.describe.form

/** "ШІ" marker on a field the AI filled and the user has not touched yet. */
export function AiBadge() {
  return (
    <span
      title={f.aiFilledHint}
      className="inline-flex items-center gap-0.5 rounded-full border border-lavender-ring bg-lavender-soft px-1.5 py-px text-[10px] font-semibold text-ai"
    >
      <Sparkles className="size-2.5" aria-hidden />
      {f.aiBadge}
    </span>
  )
}

/** "MT5" marker on a field prefilled from MT5 (M8-09) the user has not touched yet. */
export function Mt5Badge({ source }: { source: Mt5FillSource }) {
  return (
    <span
      title={f.mt5FilledHint[source]}
      className="inline-flex items-center rounded-full border border-lavender-ring bg-lavender-soft px-1.5 py-px text-[10px] font-semibold text-ai"
    >
      {f.mt5Badge}
    </span>
  )
}

interface FieldShellProps {
  fieldKey: string
  label: string
  required: boolean
  aiFilled: boolean
  /** M8-09: prefilled from MT5 (null = not). */
  mt5Fill?: Mt5FillSource | null
  missing: boolean
  error: string | null
  hint?: string
  /** Label is a <span> (group of buttons/checkboxes) instead of a <label for>. */
  group?: boolean
  children: ReactNode
}

/** Label row (required mark, AI marker, error) + control. Missing required → red edge and label. */
export function FieldShell({ fieldKey, label, required, aiFilled, mt5Fill, missing, error, hint, group, children }: FieldShellProps) {
  const id = fieldDomId(fieldKey)
  const labelClass = cn('text-xs font-medium', missing ? 'text-destructive' : 'text-muted-foreground')
  const labelContent = (
    <>
      {label}
      {required && (
        <span className={missing ? 'text-destructive' : 'text-foreground'} aria-hidden>
          {uk.common.requiredMark}
        </span>
      )}
    </>
  )
  return (
    <div
      className={cn(
        'flex flex-col gap-1.5 border-l-2 py-1 pl-3',
        missing ? 'border-destructive' : aiFilled || mt5Fill ? 'border-ai/60' : 'border-transparent',
      )}
      role={group ? 'group' : undefined}
      aria-labelledby={group ? `${id}-label` : undefined}
    >
      <div className="flex flex-wrap items-center gap-2">
        {group ? (
          <span id={`${id}-label`} className={labelClass}>
            {labelContent}
          </span>
        ) : (
          <label htmlFor={id} className={labelClass}>
            {labelContent}
          </label>
        )}
        {aiFilled && <AiBadge />}
        {mt5Fill && <Mt5Badge source={mt5Fill} />}
        {missing && <span className="text-[11px] text-destructive">{f.missing}</span>}
      </div>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}

export interface SegmentOption {
  value: string
  label: string
}

interface SegmentedProps {
  id: string
  options: readonly SegmentOption[]
  value: string | null
  /** Clicking the active option clears it (null). */
  onChange: (value: string | null) => void
  invalid?: boolean
  mono?: boolean
}

/** Single choice as a row of toggle buttons (few options, one click). */
export function Segmented({ id, options, value, onChange, invalid, mono }: SegmentedProps) {
  return (
    <div id={id} className="flex flex-wrap gap-1" aria-invalid={invalid || undefined}>
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(active ? null : option.value)}
            className={cn(
              'h-7 rounded-md border px-2.5 text-xs transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring motion-reduce:transition-none',
              mono && 'num min-w-8',
              active
                ? selectedToggleClass
                : 'border-input bg-surface text-foreground hover:bg-accent',
              invalid && !active && 'border-destructive/60',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
