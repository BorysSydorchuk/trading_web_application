import { useId } from 'react'
import { Columns3 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { uk } from '@/i18n/uk'
import { COLUMN_KEYS, DEFAULT_COLUMNS, type ColumnKey } from './columns'

interface ColumnChooserProps {
  visible: readonly ColumnKey[]
  onChange: (next: ColumnKey[]) => void
}

export function ColumnChooser({ visible, onChange }: ColumnChooserProps) {
  const id = useId()
  const visibleSet = new Set(visible)

  function toggle(key: ColumnKey) {
    const next = COLUMN_KEYS.filter((k) => (k === key ? !visibleSet.has(k) : visibleSet.has(k)))
    // At least one column stays visible.
    if (next.length > 0) onChange(next)
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" size="sm" className="h-8 text-xs">
          <Columns3 aria-hidden />
          {uk.journal.columnsButton}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2 text-sm">
        <p className="px-2 pt-1 pb-2 text-xs font-medium text-muted-foreground">{uk.journal.columnsTitle}</p>
        <ul className="grid max-h-80 grid-cols-1 overflow-y-auto">
          {COLUMN_KEYS.map((key) => (
            <li key={key}>
              <label
                htmlFor={`${id}-${key}`}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-accent/50"
              >
                <input
                  id={`${id}-${key}`}
                  type="checkbox"
                  className="size-3.5 accent-primary"
                  checked={visibleSet.has(key)}
                  onChange={() => toggle(key)}
                />
                {uk.trades.columns[key]}
              </label>
            </li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() => onChange([...DEFAULT_COLUMNS])}
          className="mt-1 w-full rounded px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-accent/50 hover:text-foreground"
        >
          {uk.journal.columnsReset}
        </button>
      </PopoverContent>
    </Popover>
  )
}
