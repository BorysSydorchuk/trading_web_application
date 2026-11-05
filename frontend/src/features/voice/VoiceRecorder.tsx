import { useEffect, useId, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { AlertCircle, Loader2, Mic } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { uk } from '@/i18n/uk'
import { AudioFileButton } from './AudioFileButton'
import { checkAudioFile, withMimeType, type AudioFileError } from './audioFile'
import { formatElapsed, MAX_RECORDING_MS } from './recorderModel'
import { useRecorder, type RecorderError, type RecorderState } from './useRecorder'

const t = uk.voice.recorder
const HOLD_KEYS = new Set([' ', 'Enter'])

export interface VoiceRecorderProps {
  /**
   * A finished recording (≥ 1 s) or a picked audio file (checked: format, ≤ 25 MB, not empty).
   * `blob.type` is the Content-Type to upload, without parameters. `durationSeconds` is null for
   * a file (unknown in the browser; the server reads it when decoding).
   */
  onRecorded: (blob: Blob, durationSeconds: number | null) => void
  disabled?: boolean
}

/**
 * Hold-to-record button (pointer or Space/Enter) plus "Завантажити аудіо" for a ready file.
 * Knows nothing about trades (reused for bias in M4).
 */
export function VoiceRecorder({ onRecorded, disabled = false }: VoiceRecorderProps) {
  const recorder = useRecorder(onRecorded)
  const hintId = useId()
  const active = recorder.phase !== 'idle'
  const [fileError, setFileError] = useState<AudioFileError | null>(null)
  useMicErrorToast(recorder.error)

  function press() {
    if (disabled) return
    setFileError(null)
    void recorder.start()
  }

  function onFile(file: File) {
    if (disabled || active) return
    const check = checkAudioFile(file)
    if (!check.ok) {
      setFileError(check.error)
      toast.error(t.fileErrors[check.error], { id: 'voice-file-error' })
      return
    }
    setFileError(null)
    onRecorded(withMimeType(file, check.mimeType), null)
  }

  function onPointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    event.preventDefault()
    // Keep receiving pointerup even when the finger/cursor drifts off the button.
    if ('setPointerCapture' in event.currentTarget) {
      try {
        event.currentTarget.setPointerCapture(event.pointerId)
      } catch {
        // Not supported (jsdom) or the pointer is already gone: release still works on the button.
      }
    }
    press()
  }

  /** Without pointer capture, leaving the button counts as letting go (pointerup would be missed). */
  function onPointerLeave(event: PointerEvent<HTMLButtonElement>) {
    const target = event.currentTarget
    const captured = 'hasPointerCapture' in target && target.hasPointerCapture(event.pointerId)
    if (!captured) recorder.stop()
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (!HOLD_KEYS.has(event.key)) return
    event.preventDefault()
    if (!event.repeat) press()
  }

  function onKeyUp(event: KeyboardEvent<HTMLButtonElement>) {
    if (!HOLD_KEYS.has(event.key)) return
    event.preventDefault()
    recorder.stop()
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant={active ? 'default' : 'outline'}
          size="sm"
          disabled={disabled && !active}
          aria-pressed={active}
          aria-describedby={hintId}
          className={cn('touch-none select-none', active && 'ring-2 ring-ring/60')}
          onPointerDown={onPointerDown}
          onPointerUp={recorder.stop}
          onPointerCancel={recorder.stop}
          onLostPointerCapture={recorder.stop}
          onPointerLeave={onPointerLeave}
          onKeyDown={onKeyDown}
          onKeyUp={onKeyUp}
          onBlur={recorder.stop}
          onContextMenu={(event) => event.preventDefault()}
        >
          {recorder.phase === 'starting' ? <Loader2 className="animate-spin" aria-hidden /> : <Mic aria-hidden />}
          {t.hold}
        </Button>
        <AudioFileButton onFile={onFile} disabled={disabled || active} />
        <span id={hintId} className="sr-only">
          {t.label}
        </span>
        <RecorderStatus state={recorder} />
      </div>
      {recorder.error && <InlineError text={t.errors[recorder.error]} />}
      {fileError && <InlineError text={t.fileErrors[fileError]} />}
    </div>
  )
}

function RecorderStatus({ state }: { state: RecorderState }) {
  if (state.phase === 'starting') {
    return (
      <span role="status" className="text-xs text-muted-foreground">
        {t.starting}
      </span>
    )
  }
  if (state.phase === 'recording') {
    return (
      <span role="status" className="flex items-center gap-2 text-xs">
        <span className="size-2 animate-pulse rounded-full bg-foreground" aria-hidden />
        <span className="num">{t.elapsed(formatElapsed(state.elapsedMs), formatElapsed(MAX_RECORDING_MS))}</span>
        <span className="text-muted-foreground">{t.recording}</span>
      </span>
    )
  }
  if (state.notice) {
    return (
      <span role="status" className="text-xs text-muted-foreground">
        {t.notices[state.notice]}
      </span>
    )
  }
  return null
}

function InlineError({ text }: { text: string }) {
  return (
    <p role="alert" className="flex max-w-prose items-start gap-1.5 text-xs text-destructive">
      <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{text}</span>
    </p>
  )
}

/** The inline message stays; the toast makes sure a failed start is noticed. */
function useMicErrorToast(error: RecorderError | null) {
  useEffect(() => {
    if (error) toast.error(t.errors[error], { id: 'voice-recorder-error' })
  }, [error])
}
