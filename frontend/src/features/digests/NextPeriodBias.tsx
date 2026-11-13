import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useBiasConfig, useBiasNote } from '@/features/bias/api'
import { BiasEditor } from '@/features/bias/BiasEditor'
import type { BiasNote } from '@/features/bias/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { digestKeys } from './api'
import { formatIsoDay, nextPeriodStart } from './format'
import type { Digest } from './types'

const n = uk.digests.nextBias

/**
 * The bias note of the next period (kind weekly/monthly, date = next period start), edited on the
 * digest screen with the existing bias editor (docs/api.md "Next-period bias"). The editor keeps
 * its state across its own create (next_bias_note_id null → id) and is reset after a delete.
 */
export function NextPeriodBias({ digest }: { digest: Digest }) {
  const queryClient = useQueryClient()
  const date = nextPeriodStart(digest.period_end)
  const [created, setCreated] = useState<number | null>(null)
  const [deleted, setDeleted] = useState<number | null>(null)
  const [generation, setGeneration] = useState(0)
  const serverId = digest.next_bias_note_id !== deleted ? digest.next_bias_note_id : null
  const noteId = created ?? serverId
  const own = created !== null
  const config = useBiasConfig()
  const note = useBiasNote(own ? null : noteId)
  const title = digest.kind === 'weekly' ? n.weekly(formatIsoDay(date)) : n.monthly(formatIsoDay(date))

  const refreshDigest = () => queryClient.invalidateQueries({ queryKey: digestKeys.period(digest.kind, digest.period_start) })
  const adopt = (saved: BiasNote) => {
    setCreated(saved.id)
    void refreshDigest()
  }
  const embedded = {
    title: <h2 className="text-sm font-semibold">{title}</h2>,
    onSaved: adopt,
    onDeleted: () => {
      setDeleted(noteId)
      setCreated(null)
      setGeneration((g) => g + 1)
      void refreshDigest()
    },
  }

  if (config.data === undefined) {
    if (config.isPending) return <Loading />
    return <LoadError error={config.error} onRetry={() => void config.refetch()} />
  }
  let loaded: BiasNote | null = null
  if (noteId !== null && !own) {
    if (note.data === undefined) {
      if (note.isPending) return <Loading />
      return <LoadError error={note.error} onRetry={() => void note.refetch()} />
    }
    loaded = note.data
  }
  return (
    <section aria-label={title}>
      <BiasEditor
        key={`${digest.kind}:${date}:${generation}`}
        symbols={config.data.symbols.map((s) => s.symbol)}
        note={loaded}
        kind={digest.kind}
        date={date}
        onCreated={adopt}
        embedded={embedded}
      />
    </section>
  )
}

function Loading() {
  return (
    <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {n.loading}
    </div>
  )
}

function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed px-4 py-3 text-sm">
      <span>{n.loadError}</span>
      <span className="text-xs text-muted-foreground">{errorText(error)}</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {uk.common.retry}
      </Button>
    </div>
  )
}
