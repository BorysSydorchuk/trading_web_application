import { aiKeyChip } from './keyState'

/**
 * Status bar chip for an AI key problem (invalid / not set / unreachable). Nothing for ok,
 * checking, or a state the backend does not send. Amber like the sync warning chip:
 * green/red are kept for P&L and the server/DB state.
 */
export function AiKeyChip({ state }: { state: unknown }) {
  const chip = aiKeyChip(state)
  if (!chip) return null
  return (
    <span
      title={chip.hint}
      className="flex shrink-0 items-center gap-1.5 rounded border border-amber-400/40 px-1.5 py-0.5"
    >
      <span className="size-2 shrink-0 rounded-full bg-amber-400" aria-hidden />
      <span className="whitespace-nowrap text-amber-400">{chip.text}</span>
    </span>
  )
}
