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
    <div role="group" aria-label={label} className={cn('inline-flex h-8 rounded-md border p-0.5', className)}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
          className={cn(
            'flex-1 rounded-sm px-2.5 text-xs font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none',
            'focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50',
            option.value === value ? 'bg-secondary text-secondary-foreground' : 'hover:text-foreground',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
