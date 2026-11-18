import { useState } from 'react'
import { MoreHorizontal } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { uk } from '@/i18n/uk'
import type { ExclusionTarget } from './ExclusionDialog'

const t = uk.exclusion

interface TradeRowMenuProps {
  trade: ExclusionTarget
  onExclusion: (trade: ExclusionTarget) => void
}

/** Journal row menu «⋯»: exclude from / return to statistics. Clicks never open the row. */
export function TradeRowMenu({ trade, onExclusion }: TradeRowMenuProps) {
  const [open, setOpen] = useState(false)
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t.menu(trade.symbol)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => e.stopPropagation()}
          className="inline-flex size-6 items-center justify-center rounded hover:bg-accent/60 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <MoreHorizontal className="size-4" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-auto p-1" onClick={(e) => e.stopPropagation()}>
        <button
          type="button"
          className="w-full rounded px-2 py-1.5 text-left text-sm whitespace-nowrap hover:bg-accent/60 focus-visible:bg-accent/60 focus-visible:outline-none"
          onClick={() => {
            setOpen(false)
            onExclusion(trade)
          }}
        >
          {trade.excluded_from_stats ? t.include : t.exclude}
        </button>
      </PopoverContent>
    </Popover>
  )
}
