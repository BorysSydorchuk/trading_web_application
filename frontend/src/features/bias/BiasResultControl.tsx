import { Check, Loader2, RotateCcw, X } from 'lucide-react'
import { uk } from '@/i18n/uk'
import { showErrorToast } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { useSetBiasResult } from './api'
import type { BiasEntry } from './types'

const r = uk.bias.result

const BUTTON = 'inline-flex h-6 items-center gap-1 rounded border px-1.5 text-[11px] transition-colors outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50'

/** "Біас справдився?" так / ні / скинути → PATCH /api/bias/entries/{id}/result (neutral colours). */
export function BiasResultControl({ entry }: { entry: BiasEntry }) {
  const mutation = useSetBiasResult()
  const busy = mutation.isPending

  function mark(wasCorrect: boolean | null) {
    mutation.mutate({ entryId: entry.id, wasCorrect }, { onError: showErrorToast })
  }

  function choice(value: boolean, label: string, Icon: typeof Check) {
    const active = entry.was_correct === value
    return (
      <button
        type="button"
        aria-pressed={active}
        disabled={busy}
        onClick={() => mark(active ? null : value)}
        className={cn(BUTTON, active ? 'border-primary/60 bg-primary text-primary-foreground' : 'border-input hover:bg-accent')}
      >
        <Icon className="size-3" aria-hidden />
        {label}
      </button>
    )
  }

  return (
    <div role="group" aria-label={r.groupLabel(entry.symbol)} className="flex items-center gap-1">
      <span className="text-[11px] text-muted-foreground">{r.question}</span>
      {choice(true, r.yes, Check)}
      {choice(false, r.no, X)}
      {entry.was_correct !== null && (
        <button type="button" disabled={busy} onClick={() => mark(null)} className={cn(BUTTON, 'border-transparent text-muted-foreground hover:bg-accent')}>
          <RotateCcw className="size-3" aria-hidden />
          {r.reset}
        </button>
      )}
      {busy && <Loader2 className="size-3 animate-spin text-muted-foreground" aria-hidden />}
    </div>
  )
}
