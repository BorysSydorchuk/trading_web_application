import { useRef, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { useBiasConfig, useBiasNote } from '@/features/bias/api'
import { BiasEditor } from '@/features/bias/BiasEditor'
import type { BiasNote } from '@/features/bias/types'
import { UnsavedChangesGuard } from '@/features/describe/UnsavedChangesGuard'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { digestKeys } from './api'
import { formatIsoDay, nextPeriodStart } from './format'
import type { Digest } from './types'

const n = uk.digests.nextBias

interface NextPeriodBiasProps {
  digest: Digest
  /** The review form has unsaved edits: the one unsaved-changes guard of the screen covers it too. */
  reviewDirty: boolean
}

/**
 * The bias note of the next period (kind weekly/monthly, date = next period start), edited on the
 * digest screen with the existing bias editor (docs/api.md "Next-period bias"). A note created
 * here is kept as `created` (the editor stays mounted, next_bias_note_id null → id); a note that
 * already existed keeps coming from its query, whose cache the save updates (audio notes stay).
 * After a delete the editor is reset.
 */
export function NextPeriodBias({ digest, reviewDirty }: NextPeriodBiasProps) {
  const queryClient = useQueryClient()
  const date = nextPeriodStart(digest.period_end)
  const [created, setCreated] = useState<BiasNote | null>(null)
  const [deleted, setDeleted] = useState<number | null>(null)
  const [generation, setGeneration] = useState(0)
  const serverId = digest.next_bias_note_id !== deleted ? digest.next_bias_note_id : null
  const noteId = created?.id ?? serverId
  const own = created !== null
  const config = useBiasConfig()
  const note = useBiasNote(own ? null : noteId)
  const title = digest.kind === 'weekly' ? n.weekly(formatIsoDay(date)) : n.monthly(formatIsoDay(date))

  const refreshDigest = () => queryClient.invalidateQueries({ queryKey: digestKeys.period(digest.kind, digest.period_start) })
  const onSaved = (saved: BiasNote) => {
    // Only a note this editor created is held here; an existing note stays on its query.
    if (noteId === null || own) setCreated(saved)
    void refreshDigest()
  }
  const embedded = {
    title: <h2 className="text-sm font-semibold">{title}</h2>,
    extraDirty: reviewDirty,
    unsavedDescription: uk.digests.unsaved,
    onSaved,
    onDeleted: () => {
      setDeleted(noteId)
      setCreated(null)
      setGeneration((g) => g + 1)
      void refreshDigest()
    },
  }

  if (config.data === undefined) {
    if (config.isPending) return <Loading reviewDirty={reviewDirty} />
    return <LoadError error={config.error} onRetry={() => void config.refetch()} reviewDirty={reviewDirty} />
  }
  let loaded: BiasNote | null = created
  if (noteId !== null && !own) {
    if (note.data === undefined) {
      if (note.isPending) return <Loading reviewDirty={reviewDirty} />
      return <LoadError error={note.error} onRetry={() => void note.refetch()} reviewDirty={reviewDirty} />
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
        onCreated={onSaved}
        embedded={embedded}
      />
    </section>
  )
}

/** Without the bias editor (loading, error) the review edits still need the guard. */
function ReviewGuard({ dirty }: { dirty: boolean }) {
  const allowLeaveRef = useRef(false)
  return <UnsavedChangesGuard dirty={dirty} allowLeaveRef={allowLeaveRef} description={uk.digests.unsaved} />
}

function Loading({ reviewDirty }: { reviewDirty: boolean }) {
  return (
    <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {n.loading}
      <ReviewGuard dirty={reviewDirty} />
    </div>
  )
}

function LoadError({ error, onRetry, reviewDirty }: { error: unknown; onRetry: () => void; reviewDirty: boolean }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed px-4 py-3 text-sm">
      <span>{n.loadError}</span>
      <span className="text-xs text-muted-foreground">{errorText(error)}</span>
      <Button variant="outline" size="sm" onClick={onRetry}>
        {uk.common.retry}
      </Button>
      <ReviewGuard dirty={reviewDirty} />
    </div>
  )
}
