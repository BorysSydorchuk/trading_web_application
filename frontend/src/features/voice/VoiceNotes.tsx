import { useEffect, useEffectEvent, useRef, useState } from 'react'
import type { UseMutationResult } from '@tanstack/react-query'
import { AlertCircle, Loader2, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { AudioNoteRow } from './AudioNoteRow'
import { useAudioNotes, useRetryAudio } from './api'
import { notesToInsert, orderedNoteIds } from './notesModel'
import type { AudioNote } from './types'
import { VoiceRecorder } from './VoiceRecorder'

const t = uk.voice.upload

/** Texts that name the owner of the notes (a trade, a bias note). */
export interface VoiceNotesLabels {
  title: string
  listLabel: string
  hint: string
}

/** Uploads one blob for the owner and answers with the new AudioNote. */
export type AudioUpload = UseMutationResult<AudioNote, Error, Blob>

interface VoiceNotesProps {
  /** The owner's audio_notes when the page opened (oldest first). */
  initialNotes: readonly AudioNote[]
  upload: AudioUpload
  /** Append a transcript to the text box. */
  onTranscript: (transcript: string) => void
  /** True while a recording exists only in the browser (uploading or upload failed). */
  onUnsentChange: (unsent: boolean) => void
  labels: VoiceNotesLabels
}

/**
 * Recorder + the owner's voice notes (no owner knowledge: the caller passes the upload).
 * A note that finishes while the page is open goes into the text box once; notes that were
 * already done get a "Вставити в текст" button instead (DECISIONS M3-06).
 */
export function VoiceNotes({ initialNotes, upload: mutation, onTranscript, onUnsentChange, labels }: VoiceNotesProps) {
  const [doneAtOpen] = useState(() => new Set(initialNotes.filter((n) => n.status === 'done').map((n) => n.id)))
  const [uploadedIds, setUploadedIds] = useState<number[]>([])
  const [manuallyInserted, setManuallyInserted] = useState<ReadonlySet<number>>(new Set())
  const insertedRef = useRef(new Set<number>())
  const ids = orderedNoteIds(initialNotes, uploadedIds)
  const queries = useAudioNotes(ids, initialNotes)
  const notes = queries.map((query) => query.data)
  const upload = useKeptUpload(mutation, (note) => setUploadedIds((prev) => [...prev, note.id]))
  const retry = useRetryAudio()

  const unsent = upload.pending || upload.failed !== null
  const reportUnsent = useEffectEvent((value: boolean) => onUnsentChange(value))
  useEffect(() => reportUnsent(unsent), [unsent])

  const insertFinished = useEffectEvent(() => {
    for (const note of notesToInsert(notes, doneAtOpen, insertedRef.current)) {
      insertedRef.current.add(note.id)
      onTranscript(note.transcript ?? '')
    }
  })
  const doneKey = notes.flatMap((note) => (note?.status === 'done' ? [note.id] : [])).join(',')
  useEffect(() => insertFinished(), [doneKey])

  function insertManually(note: AudioNote) {
    if (insertedRef.current.has(note.id)) return
    insertedRef.current.add(note.id)
    onTranscript(note.transcript ?? '')
    setManuallyInserted((prev) => new Set([...prev, note.id]))
  }

  return (
    <div role="group" aria-label={labels.title} className="flex flex-col gap-2">
      {/* Blocked until a failed upload is re-sent or discarded, so that blob is never dropped. */}
      <VoiceRecorder onRecorded={upload.send} disabled={unsent} />
      <UploadState upload={upload} />
      {ids.length > 0 && (
        <>
          <ul aria-label={labels.listLabel} className="flex flex-col gap-1.5">
            {ids.map((id, i) => {
              const note = notes[i]
              return (
                <AudioNoteRow
                  key={id}
                  note={note}
                  index={i + 1}
                  pollError={queries[i]?.isError ?? false}
                  inserted={!doneAtOpen.has(id) || manuallyInserted.has(id)}
                  onInsert={() => note && insertManually(note)}
                  onRetry={() => retry.mutate(id)}
                  retrying={retry.isPending && retry.variables === id}
                />
              )
            })}
          </ul>
          <p className="text-xs text-muted-foreground">{labels.hint}</p>
        </>
      )}
    </div>
  )
}

interface FailedUpload {
  blob: Blob
  /** Local replay while the server does not have the file; null where object URLs are missing. */
  url: string | null
}

function objectUrl(blob: Blob): string | null {
  return typeof URL.createObjectURL === 'function' ? URL.createObjectURL(blob) : null
}

function revoke(failed: FailedUpload | null): void {
  if (failed?.url) URL.revokeObjectURL(failed.url)
}

/** Upload with a kept local copy: a failed upload can be played and sent again. */
function useKeptUpload(mutation: AudioUpload, onUploaded: (note: AudioNote) => void) {
  const [failed, setFailed] = useState<FailedUpload | null>(null)
  const failedRef = useRef<FailedUpload | null>(null)

  useEffect(() => () => revoke(failedRef.current), [])

  function remember(next: FailedUpload | null) {
    revoke(failedRef.current)
    failedRef.current = next
    setFailed(next)
  }

  /** The failed blob stays until its re-send succeeds or the user discards it; another blob is refused. */
  function send(blob: Blob) {
    const kept = failedRef.current
    if (kept && kept.blob !== blob) return
    mutation.mutate(blob, {
      onSuccess: (note) => {
        remember(null)
        onUploaded(note)
      },
      onError: () => {
        if (failedRef.current?.blob !== blob) remember({ blob, url: objectUrl(blob) })
      },
    })
  }

  function discard() {
    remember(null)
    mutation.reset()
  }

  return { send, discard, pending: mutation.isPending, error: mutation.error, failed }
}

function UploadState({ upload }: { upload: ReturnType<typeof useKeptUpload> }) {
  if (upload.pending) {
    return (
      <p role="status" className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        {t.uploading}
      </p>
    )
  }
  const { failed } = upload
  if (!failed) return null
  return (
    <div className="flex flex-col gap-1.5 rounded-md border border-dashed px-3 py-2 text-xs">
      <p role="alert" className="flex items-start gap-1.5 text-destructive">
        <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden />
        <span>
          {t.uploadFailed} {errorText(upload.error)}
        </span>
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="button" variant="outline" size="sm" className="h-7 text-xs" onClick={() => upload.send(failed.blob)}>
          <Upload aria-hidden />
          {t.retryUpload}
        </Button>
        <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={upload.discard}>
          <Trash2 aria-hidden />
          {t.discard}
        </Button>
        <span className="text-muted-foreground">{t.localCopy}</span>
      </div>
      <p className="text-muted-foreground">{t.resolveFirst}</p>
      {failed.url && <audio controls src={failed.url} className="h-8 w-full max-w-md" aria-label={t.localPlayer} />}
    </div>
  )
}
