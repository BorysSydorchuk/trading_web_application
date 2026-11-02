import { useId } from 'react'
import { ChevronDownIcon } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

export interface FilterOption {
  value: string
  label: string
}

interface MultiSelectFilterProps {
  label: string
  options: readonly FilterOption[]
  selected: readonly string[]
  onChange: (selected: string[]) => void
  /** Monospace option labels (symbols, logins). */
  mono?: boolean
}

/** Compact filter button + popover with checkboxes. Empty selection means "all". */
export function MultiSelectFilter({ label, options, selected, onChange, mono }: MultiSelectFilterProps) {
  const id = useId()
  const f = uk.journal.filters
  const selectedSet = new Set(selected)

  let summary: string = f.all
  if (selected.length === 1) {
    summary = options.find((o) => o.value === selected[0])?.label ?? selected[0] ?? f.all
  } else if (selected.length > 1) {
    summary = f.selected(selected.length)
  }

  function toggle(value: string) {
    if (selectedSet.has(value)) {
      onChange(selected.filter((v) => v !== value))
      return
    }
    // Option order stays stable; selected values without an option (from the URL, options
    // still loading or failed) are kept, not silently dropped.
    const known = new Set(options.map((o) => o.value))
    const ordered = options.map((o) => o.value).filter((v) => v === value || selectedSet.has(v))
    onChange([...ordered, ...selected.filter((v) => !known.has(v))])
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            'flex h-8 items-center gap-1.5 rounded-md border border-input px-2.5 text-xs shadow-xs hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none dark:bg-input/30',
            selected.length > 0 && 'border-ring',
          )}
        >
          <span className="text-muted-foreground">{label}</span>
          <span className="max-w-40 truncate">{summary}</span>
          <ChevronDownIcon className="size-3.5 text-muted-foreground" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-60 p-2 text-sm">
        {options.length === 0 ? (
          <p className="px-2 py-1.5 text-xs text-muted-foreground">{f.noOptions}</p>
        ) : (
          <ul className="flex max-h-72 flex-col overflow-y-auto" aria-label={label}>
            {options.map((option, index) => (
              <li key={option.value}>
                <label
                  htmlFor={`${id}-${index}`}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-accent/50"
                >
                  <input
                    id={`${id}-${index}`}
                    type="checkbox"
                    className="size-3.5 accent-primary"
                    checked={selectedSet.has(option.value)}
                    onChange={() => toggle(option.value)}
                  />
                  <span className={cn('truncate', mono && 'num')}>{option.label}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="mt-1 w-full rounded px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-accent/50 hover:text-foreground"
          >
            {f.clear}
          </button>
        )}
      </PopoverContent>
    </Popover>
  )
}
