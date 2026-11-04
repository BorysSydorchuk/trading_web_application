import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { AlertCircle, Loader2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { AudioNoteRow } from '@/features/voice/AudioNoteRow'
import { useAudioNotes, useRetryAudio, useUploadTradeAudio } from '@/features/voice/api'
import { notesToInsert, orderedNoteIds } from '@/features/voice/notesModel'
import type { AudioNote } from '@/features/voice/types'
import { VoiceRecorder } from '@/features/voice/VoiceRecorder'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'

const t = uk.describe.voice

interface DescribeVoiceProps {
  tradeId: number
  /** TradeDetail.audio_notes when the page opened (oldest first). */
  tradeNotes: readonly AudioNote[]
  /** Append a transcript to the description text box. */
  onTranscript: (transcript: string) => void
}

/**
 * Recorder + this trade's voice notes. A note that finishes while the page is open goes into the
 * text box once; notes that were already done get a "Вставити в текст" button instead.
 */
export function DescribeVoice({ tradeId, tradeNotes, onTranscript }: DescribeVoiceProps) {
  const [doneAtOpen] = useState(() => new Set(tradeNotes.filter((n) => n.status === 'done').map((n) => n.id)))
  const [uploadedIds, setUploadedIds] = useState<number[]>([])
  const [manuallyInserted, setManuallyInserted] = useState<ReadonlySet<number>>(new Set())
  const insertedRef = useRef(new Set<number>())
  const ids = orderedNoteIds(tradeNotes, uploadedIds)
  const queries = useAudioNotes(ids, tradeNotes)
  const notes = queries.map((query) => query.data)
  const upload = useTradeUpload(tradeId, (note) => setUploadedIds((prev) => [...prev, note.id]))
  const retry = useRetryAudio()

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
    <div role="group" aria-label={t.title} className="flex flex-col gap-2">
      <VoiceRecorder onRecorded={upload.send} disabled={upload.pending} />
      <UploadState upload={upload} />
      {ids.length > 0 && (
        <>
          <ul aria-label={t.title} className="flex flex-col gap-1.5">
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
          <p className="text-xs text-muted-foreground">{t.hint}</p>
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
function useTradeUpload(tradeId: number, onUploaded: (note: AudioNote) => void) {
  const mutation = useUploadTradeAudio(tradeId)
  const [failed, setFailed] = useState<FailedUpload | null>(null)
  const failedRef = useRef<FailedUpload | null>(null)

  useEffect(() => () => revoke(failedRef.current), [])

  function remember(next: FailedUpload | null) {
    revoke(failedRef.current)
    failedRef.current = next
    setFailed(next)
  }

  function send(blob: Blob) {
    remember(null)
    mutation.mutate(blob, {
      onSuccess: onUploaded,
      onError: () => remember({ blob, url: objectUrl(blob) }),
    })
  }

  return { send, pending: mutation.isPending, error: mutation.error, failed }
}

function UploadState({ upload }: { upload: ReturnType<typeof useTradeUpload> }) {
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
        <span className="text-muted-foreground">{t.localCopy}</span>
      </div>
      {failed.url && <audio controls src={failed.url} className="h-8 w-full max-w-md" aria-label={t.localPlayer} />}
    </div>
  )
}
