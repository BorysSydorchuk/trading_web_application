import { cn } from '@/lib/utils'

export interface ToggleOption<T extends string> {
  value: T
  label: string
}

interface SegmentedToggleProps<T extends string> {
  label: string
  value: T
  options: readonly ToggleOption<T>[]
  onChange: (value: T) => void
  disabled?: boolean
  className?: string
}

/** A group of pressed/unpressed buttons (one selected). Neutral colours: green/red is for P&L only. */
export function SegmentedToggle<T extends string>({ label, value, options, onChange, disabled, className }: SegmentedToggleProps<T>) {
  return (
    <div role="group" aria-label={label} className={cn('inline-flex h-9 gap-0.5 rounded-[10px] border border-line bg-track p-0.5', className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            'flex-1 rounded-[8px] px-2.5 text-xs whitespace-nowrap transition-colors outline-none motion-reduce:transition-none',
            'focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-50',
            option.value === value ? 'bg-surface font-semibold text-ink shadow-segment' : 'font-medium text-ink-muted hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
