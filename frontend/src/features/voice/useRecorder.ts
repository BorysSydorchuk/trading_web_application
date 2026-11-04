/**
 * Hold-to-record with MediaRecorder. `start()` on press, `stop()` on release. The microphone is
 * released after every recording (and on unmount). Presses under 1 s are discarded; 10 min stops.
 */
import { useEffect, useRef, useState } from 'react'
import {
  baseMimeType,
  durationSeconds,
  MAX_RECORDING_MS,
  micErrorKind,
  MIN_RECORDING_MS,
  pickMimeType,
  type MicErrorKind,
} from './recorderModel'

const TICK_MS = 250

export type RecorderError = MicErrorKind | 'recorder'
export type RecorderNotice = 'tooShort' | 'maxReached' | 'interrupted'

export interface RecorderState {
  phase: 'idle' | 'starting' | 'recording'
  elapsedMs: number
  error: RecorderError | null
  notice: RecorderNotice | null
}

const IDLE: RecorderState = { phase: 'idle', elapsedMs: 0, error: null, notice: null }

/** One press. Lives in a ref; never rendered. */
interface Session {
  stream: MediaStream | null
  recorder: MediaRecorder | null
  chunks: Blob[]
  startedAt: number
  durationMs: number
  /** Released while the microphone was still being opened. */
  released: boolean
  stopping: boolean
  maxReached: boolean
  failed: boolean
  ticker: number | undefined
  limit: number | undefined
}

function newSession(): Session {
  return {
    stream: null,
    recorder: null,
    chunks: [],
    startedAt: 0,
    durationMs: 0,
    released: false,
    stopping: false,
    maxReached: false,
    failed: false,
    ticker: undefined,
    limit: undefined,
  }
}

function releaseMic(stream: MediaStream | null): void {
  for (const track of stream?.getTracks() ?? []) track.stop()
}

function clearTimers(session: Session): void {
  window.clearInterval(session.ticker)
  window.clearTimeout(session.limit)
}

function finishNotice(session: Session): RecorderNotice | null {
  if (session.failed) return 'interrupted'
  return session.maxReached ? 'maxReached' : null
}

function createRecorder(stream: MediaStream): MediaRecorder {
  const mimeType = pickMimeType((type) => MediaRecorder.isTypeSupported(type))
  return new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
}

/** Why recording cannot start in this browser, or null. */
function unavailableReason(): RecorderError | null {
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) return 'no_mic'
  if (typeof MediaRecorder === 'undefined') return 'unsupported'
  return null
}

export function useRecorder(onRecorded: (blob: Blob, seconds: number) => void) {
  const [state, setState] = useState<RecorderState>(IDLE)
  const sessionRef = useRef<Session | null>(null)
  const onRecordedRef = useRef(onRecorded)

  useEffect(() => {
    onRecordedRef.current = onRecorded
  }, [onRecorded])

  // Leaving the page while recording: drop the recording, free the microphone.
  useEffect(
    () => () => {
      const session = sessionRef.current
      sessionRef.current = null
      if (!session) return
      clearTimers(session)
      if (session.recorder && session.recorder.state !== 'inactive') session.recorder.stop()
      releaseMic(session.stream)
    },
    [],
  )

  function finish(session: Session): void {
    releaseMic(session.stream)
    if (sessionRef.current !== session) return
    sessionRef.current = null
    const long = session.durationMs >= MIN_RECORDING_MS
    const blob = new Blob(session.chunks, { type: baseMimeType(session.recorder?.mimeType || session.chunks[0]?.type) })
    // A browser error mid-recording: keep what was recorded when it is a real note (≥ 1 s).
    if (session.failed && (!long || blob.size === 0)) return setState({ ...IDLE, error: 'recorder' })
    if (!long) return setState({ ...IDLE, notice: 'tooShort' })
    if (blob.size === 0) return setState({ ...IDLE, error: 'recorder' })
    setState({ ...IDLE, notice: finishNotice(session) })
    onRecordedRef.current(blob, durationSeconds(session.durationMs))
  }

  function stop(maxReached = false): void {
    const session = sessionRef.current
    if (!session) return
    if (!session.recorder) {
      session.released = true
      return
    }
    if (session.stopping) return
    session.stopping = true
    session.maxReached = maxReached
    session.durationMs = Date.now() - session.startedAt
    clearTimers(session)
    try {
      session.recorder.stop()
    } catch {
      // Already inactive (older browsers throw InvalidStateError after an error): finish now.
      finish(session)
    }
  }

  function begin(session: Session, stream: MediaStream): void {
    const recorder = createRecorder(stream)
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) session.chunks.push(event.data)
    }
    recorder.onstop = () => finish(session)
    recorder.onerror = () => {
      session.failed = true
      stop()
    }
    recorder.start()
    session.recorder = recorder
    session.startedAt = Date.now()
    session.ticker = window.setInterval(
      () => setState((prev) => ({ ...prev, elapsedMs: Date.now() - session.startedAt })),
      TICK_MS,
    )
    session.limit = window.setTimeout(() => stop(true), MAX_RECORDING_MS)
    setState({ ...IDLE, phase: 'recording' })
  }

  async function start(): Promise<void> {
    if (sessionRef.current) return
    const unavailable = unavailableReason()
    if (unavailable) return setState({ ...IDLE, error: unavailable })
    const session = newSession()
    sessionRef.current = session
    setState({ ...IDLE, phase: 'starting' })
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      if (sessionRef.current === session) sessionRef.current = null
      return setState({ ...IDLE, error: micErrorKind(error) })
    }
    session.stream = stream
    if (sessionRef.current !== session) return releaseMic(stream)
    if (session.released) {
      // Let go before the microphone was open: a tap, not a note.
      releaseMic(stream)
      sessionRef.current = null
      return setState({ ...IDLE, notice: 'tooShort' })
    }
    try {
      begin(session, stream)
    } catch {
      clearTimers(session)
      releaseMic(stream)
      sessionRef.current = null
      setState({ ...IDLE, error: 'recorder' })
    }
  }

  return { ...state, start, stop: () => stop() }
}
