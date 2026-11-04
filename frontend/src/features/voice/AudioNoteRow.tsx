import { AlertCircle, Check, Loader2, RotateCcw, TextCursorInput } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { progressPercent, transcriptionErrorText } from './notesModel'
import type { AudioNote } from './types'

const t = uk.voice.notes

export interface AudioNoteRowProps {
  /** Undefined while the note is being loaded. */
  note: AudioNote | undefined
  /** 1-based number shown to the user. */
  index: number
  /** The last poll failed (the next one retries). */
  pollError: boolean
  /** The transcript is already in the text box. */
  inserted: boolean
  onInsert: () => void
  onRetry: () => void
  retrying: boolean
}

/** One voice note: queue / progress / done / failed, with replay for finished and failed notes. */
export function AudioNoteRow(props: AudioNoteRowProps) {
  const { note, index, pollError } = props
  const label = t.label(index)
  return (
    <li aria-label={label} className="flex flex-col gap-1.5 rounded-md border px-3 py-2 text-xs">
      <div className="flex min-h-7 flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{label}</span>
        <NoteStatus {...props} />
      </div>
      {note?.status === 'failed' && (
        <p role="alert" className="flex items-start gap-1.5 text-destructive">
          <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>
            {t.failed} {transcriptionErrorText(note.error_code)} {t.audioKept}
          </span>
        </p>
      )}
      {pollError && <p className="text-muted-foreground">{t.pollError}</p>}
      {(note?.status === 'done' || note?.status === 'failed') && (
        <audio controls preload="none" src={note.file_url} aria-label={t.player(index)} className="h-8 w-full max-w-md" />
      )}
    </li>
  )
}

function NoteStatus({ note, index, inserted, onInsert, onRetry, retrying }: AudioNoteRowProps) {
  if (note === undefined || note.status === 'pending') {
    return (
      <span role="status" className="flex items-center gap-1.5 text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        {t.pending}
      </span>
    )
  }
  if (note.status === 'processing') return <Progress note={note} index={index} />
  if (note.status === 'failed') {
    return (
      <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={onRetry} disabled={retrying}>
        {retrying ? <Loader2 className="animate-spin" aria-hidden /> : <RotateCcw aria-hidden />}
        {t.retry}
      </Button>
    )
  }
  return <DoneStatus note={note} inserted={inserted} onInsert={onInsert} />
}

function Progress({ note, index }: { note: AudioNote; index: number }) {
  const percent = progressPercent(note)
  return (
    <span className="flex items-center gap-2 text-muted-foreground">
      {/* Not a live region: a new percentage every second would flood screen readers; the bar carries it. */}
      <span className="num">{t.processing(percent)}</span>
      <span
        role="progressbar"
        aria-label={t.progress(index)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        className="h-1.5 w-32 overflow-hidden rounded-full bg-muted"
      >
        <span className="block h-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
      </span>
    </span>
  )
}

function DoneStatus({ note, inserted, onInsert }: { note: AudioNote; inserted: boolean; onInsert: () => void }) {
  const empty = (note.transcript ?? '').trim() === ''
  return (
    <span className="flex flex-wrap items-center gap-2 text-muted-foreground">
      <span className="flex items-center gap-1.5">
        <Check className="size-3.5" aria-hidden />
        {empty ? t.emptyTranscript : t.done}
      </span>
      {!empty && inserted && <span>{t.inserted}</span>}
      {!empty && !inserted && (
        <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={onInsert}>
          <TextCursorInput aria-hidden />
          {t.insert}
        </Button>
      )}
    </span>
  )
}
