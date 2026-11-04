/** Pure helpers for the list of voice notes (status, errors, transcript insertion). */
import { uk } from '@/i18n/uk'
import type { AudioNote } from './types'

/** The UI polls GET /api/audio/{id} this often while a note is queued or running. */
export const POLL_INTERVAL_MS = 1_000

export function isActive(note: AudioNote | undefined): boolean {
  return note?.status === 'pending' || note?.status === 'processing'
}

/** 0.453 → 45; null / out of range → clamped to 0–100. */
export function progressPercent(note: AudioNote): number {
  const value = note.progress ?? 0
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, Math.floor(value * 100)))
}

/** `errors.transcription.<error_code>`, unknown or missing codes → `transcription_failed`. */
export function transcriptionErrorText(code: string | null): string {
  const texts: Readonly<Record<string, string>> = uk.errors.transcription
  if (code !== null && Object.hasOwn(texts, code)) return texts[code] ?? uk.errors.transcription.transcription_failed
  return uk.errors.transcription.transcription_failed
}

/** Appends a transcript to the description: a blank line between, nothing for an empty transcript. */
export function appendTranscript(text: string, transcript: string | null): string {
  const addition = (transcript ?? '').trim()
  if (addition === '') return text
  const current = text.replace(/\s+$/, '')
  return current === '' ? addition : `${current}\n\n${addition}`
}

/** Trade notes (oldest first), then notes uploaded on this page that the trade does not list yet. */
export function orderedNoteIds(tradeNotes: readonly AudioNote[], uploadedIds: readonly number[]): number[] {
  const ids = tradeNotes.map((note) => note.id)
  const known = new Set(ids)
  return [...ids, ...uploadedIds.filter((id) => !known.has(id))]
}

/**
 * Done notes whose transcript goes into the text box now: not done when the page opened,
 * not inserted before, with a non-empty transcript.
 */
export function notesToInsert(
  notes: readonly (AudioNote | undefined)[],
  doneAtOpen: ReadonlySet<number>,
  inserted: ReadonlySet<number>,
): AudioNote[] {
  return notes.filter(
    (note): note is AudioNote =>
      note !== undefined && note.status === 'done' && !doneAtOpen.has(note.id) && !inserted.has(note.id),
  )
}
