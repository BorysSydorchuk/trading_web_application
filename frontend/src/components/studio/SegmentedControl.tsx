import { useRef, type KeyboardEvent } from 'react'
import { cn } from '@/lib/utils'

export interface SegmentedOption<T extends string> {
  value: T
  label: string
}

export interface SegmentedControlProps<T extends string> {
  /** Accessible name of the group. */
  label: string
  value: T
  options: readonly SegmentedOption<T>[]
  onChange: (value: T) => void
  disabled?: boolean
  className?: string
}

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown'])
const PREV_KEYS = new Set(['ArrowLeft', 'ArrowUp'])

/** Index the keyboard moves to, or null for keys the group does not handle. */
function targetIndex(key: string, current: number, count: number): number | null {
  if (NEXT_KEYS.has(key)) return (current + 1) % count
  if (PREV_KEYS.has(key)) return (current - 1 + count) % count
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  return null
}

/**
 * Pill-shaped radio group (one option selected). WAI-ARIA radio pattern: one tab stop (the selected
 * option), arrows/Home/End move and select. Neutral colours: green/red is for P&L only.
 */
export function SegmentedControl<T extends string>({ label, value, options, onChange, disabled, className }: SegmentedControlProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  // -1 when `value` is not among the options: nothing is checked, the first option keeps the tab stop.
  const selected = options.findIndex((option) => option.value === value)
  const tabStop = selected === -1 ? 0 : selected

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = targetIndex(event.key, index, options.length)
    if (next === null) return
    event.preventDefault()
    const option = options[next]
    if (!option) return
    onChange(option.value)
    refs.current[next]?.focus()
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-disabled={disabled || undefined}
      data-slot="studio-segmented"
      className={cn('inline-flex gap-1 rounded-xl border border-line bg-surface/70 p-1', className)}
    >
      {options.map((option, index) => {
        const checked = index === selected
        return (
          <button
            key={option.value}
            ref={(element) => {
              refs.current[index] = element
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={index === tabStop ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              'rounded-[9px] px-3 py-1.5 text-xs whitespace-nowrap outline-none',
              'transition-colors duration-150 motion-reduce:transition-none',
              'focus-visible:ring-[3px] focus-visible:ring-ring disabled:opacity-50',
              checked ? 'bg-surface font-semibold text-ink shadow-segment' : 'text-ink-muted hover:text-ink',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
