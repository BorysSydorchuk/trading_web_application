import { Link } from 'react-router'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { uk } from '@/i18n/uk'
import { aiKeyChip } from './keyState'

/**
 * Status bar chip for an AI key problem (invalid / not set / unreachable). Nothing for ok,
 * checking, or a state the backend does not send. Amber like the sync warning chip:
 * green/red are kept for P&L and the server/DB state. The hint opens in a popover
 * (keyboard, touch and screen readers), like the sync chips.
 */
export function AiKeyChip({ state }: { state: unknown }) {
  const chip = aiKeyChip(state)
  if (!chip) return null
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`${chip.text}. ${chip.hint}`}
          className="flex shrink-0 items-center gap-1.5 rounded border border-amber-400/40 px-1.5 py-0.5 hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <span className="size-2 shrink-0 rounded-full bg-amber-400" aria-hidden />
          <span className="whitespace-nowrap text-amber-400">{chip.text}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="flex w-80 flex-col gap-2 text-xs">
        <p className="text-sm font-medium text-amber-400">{chip.text}</p>
        <p className="text-muted-foreground">{chip.hint}</p>
        <Link to="/settings" className="self-start underline underline-offset-2 hover:text-foreground">
          {uk.aiKey.chip.openSettings}
        </Link>
      </PopoverContent>
    </Popover>
  )
}
