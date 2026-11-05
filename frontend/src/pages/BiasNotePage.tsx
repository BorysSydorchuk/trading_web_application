import { useState, type ReactNode } from 'react'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { Link, useLocation, useParams, useSearchParams } from 'react-router'
import { Button } from '@/components/ui/button'
import { useBiasConfig, useBiasNote } from '@/features/bias/api'
import { BiasEditor } from '@/features/bias/BiasEditor'
import { defaultKind } from '@/features/bias/period'
import { isBiasKind, type BiasKind, type BiasNote } from '@/features/bias/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { brusselsToday, isIsoDate } from '@/lib/time'

const e = uk.bias.editor
const NEW_ID = 'new'

function parseNoteId(raw: string | undefined): number | null {
  if (!raw || !/^\d+$/.test(raw)) return null
  const id = Number(raw)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

/** Kind and date of a new note: `?kind=…&date=…` when valid, else by Brussels time / today. */
function newNoteStart(params: URLSearchParams): { kind: BiasKind; date: string } {
  const kind = params.get('kind')
  const date = params.get('date') ?? ''
  return { kind: isBiasKind(kind) ? kind : defaultKind(), date: isIsoDate(date) ? date : brusselsToday() }
}

/**
 * /bias/new?kind=…&date=… and /bias/:id — the bias note editor. A note created on this page
 * (for a voice upload, before the entries are saved) moves the URL to /bias/<id> but keeps the
 * same editor and its unsaved edits.
 */
export function BiasNotePage() {
  const rawId = useParams().id
  const isNew = rawId === NEW_ID
  const noteId = isNew ? null : parseNoteId(rawId)
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="sm" className="h-7 text-xs">
          <Link to="/bias">
            <ArrowLeft aria-hidden />
            {e.back}
          </Link>
        </Button>
        <h1 className="text-lg font-semibold tracking-tight">{isNew ? e.newTitle : e.editTitle}</h1>
      </div>
      {!isNew && noteId === null ? <Notice text={uk.errors.not_found} /> : <EditorContent noteId={noteId} />}
    </section>
  )
}

function EditorContent({ noteId }: { noteId: number | null }) {
  const location = useLocation()
  const [params] = useSearchParams()
  const [created, setCreated] = useState<{ id: number; key: string } | null>(null)
  const ownNote = noteId !== null && created?.id === noteId
  const config = useBiasConfig()
  const note = useBiasNote(ownNote ? null : noteId)
  const editorKey = noteId === null ? `new:${location.key}` : ownNote ? created.key : `note:${noteId}`

  if (config.data === undefined) {
    if (config.isPending) return <Loading text={e.configLoading} />
    return <LoadError text={e.configError} error={config.error} onRetry={() => void config.refetch()} busy={config.isFetching} />
  }
  const symbols = config.data.symbols.map((s) => s.symbol)
  const onCreated = (saved: BiasNote) => setCreated({ id: saved.id, key: editorKey })

  let loaded: BiasNote | null = null
  if (noteId !== null && !ownNote) {
    if (note.data === undefined) {
      if (note.isPending) return <Loading text={e.loading} />
      return <LoadError text={e.loadError} error={note.error} onRetry={() => void note.refetch()} busy={note.isFetching} />
    }
    loaded = note.data
  }
  const start = loaded ? { kind: loaded.kind, date: loaded.period_date } : newNoteStart(params)
  // Same element type and position for a new note and the note it created, so the editor is kept.
  return <BiasEditor key={editorKey} symbols={symbols} note={loaded} kind={start.kind} date={start.date} onCreated={onCreated} />
}

function Loading({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {text}
    </div>
  )
}

function Notice({ text }: { text: ReactNode }) {
  return (
    <div className="flex min-h-32 items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center">
      <p className="text-muted-foreground">{text}</p>
    </div>
  )
}

function LoadError({ text, error, onRetry, busy }: { text: string; error: unknown; onRetry: () => void; busy: boolean }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-8 text-center">
      <p>{text}</p>
      <p className="text-xs text-muted-foreground">{errorText(error)}</p>
      <Button variant="outline" size="sm" onClick={onRetry} disabled={busy}>
        {busy && <Loader2 className="animate-spin" aria-hidden />}
        {uk.common.retry}
      </Button>
    </div>
  )
}
