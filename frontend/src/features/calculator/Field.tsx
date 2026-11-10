import type { ReactNode } from 'react'
import { Input } from '@/components/ui/input'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

interface FieldProps {
  id: string
  label: string
  required?: boolean
  error?: string
  hint?: string
  /** The control is a button group labelled by itself: render the caption as plain text, not a <label>. */
  group?: boolean
  /** Extra control on the label row (e.g. a mode toggle). */
  aside?: ReactNode
  className?: string
  children: ReactNode
}

/** Label + control + hint/error, error linked via aria-describedby (`${id}-msg`). */
export function Field({ id, label, required, error, hint, group, aside, className, children }: FieldProps) {
  const Caption = group ? 'span' : 'label'
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
      <div className="flex min-h-5 items-center justify-between gap-2">
        <Caption htmlFor={group ? undefined : id} className="text-xs font-medium text-muted-foreground">
          {label}
          {required && (
            <span className="text-foreground" aria-hidden>
              {uk.common.requiredMark}
            </span>
          )}
        </Caption>
        {aside}
      </div>
      {children}
      <p id={`${id}-msg`} className={cn('text-xs', error ? 'text-destructive' : 'text-muted-foreground', !error && !hint && 'sr-only')}>
        {error ?? hint}
      </p>
    </div>
  )
}

interface DecimalInputProps {
  id: string
  value: string
  onChange: (value: string) => void
  invalid: boolean
  disabled?: boolean
  placeholder?: string
}

/** Decimal text input: kept exactly as typed (the payload trims and turns a comma into a dot). */
export function DecimalInput({ id, value, onChange, invalid, disabled, placeholder }: DecimalInputProps) {
  return (
    <Input
      id={id}
      inputMode="decimal"
      autoComplete="off"
      spellCheck={false}
      className="num text-right"
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      aria-required
      aria-describedby={`${id}-msg`}
      disabled={disabled}
    />
  )
}
