/** Pure checks for an audio file picked with "Завантажити аудіо" (no browser state). */

/** Server limit (docs/api.md): 25 MB = 25 MiB, inclusive. */
export const MAX_AUDIO_FILE_BYTES = 25 * 1024 * 1024

/**
 * Extension → Content-Type the server accepts. The extension wins over `File.type`: browsers
 * report "", "audio/opus", "audio/x-m4a" or "video/webm" for the same files.
 */
const MIME_BY_EXTENSION: Readonly<Record<string, string>> = {
  ogg: 'audio/ogg',
  opus: 'audio/ogg',
  m4a: 'audio/mp4',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  webm: 'audio/webm',
}

/** For `<input type="file" accept>`; `audio/*` lets mobile pickers show audio apps too. */
export const AUDIO_FILE_ACCEPT = [...Object.keys(MIME_BY_EXTENSION).map((ext) => `.${ext}`), 'audio/*'].join(',')

export type AudioFileError = 'format' | 'too_large' | 'empty'

export type AudioFileCheck = { ok: true; mimeType: string } | { ok: false; error: AudioFileError }

/** "audio_2026-11-04_23-24-49.OGG" → "ogg"; no dot → "". */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1).trim().toLowerCase()
}

/** Content-Type for this file name, or null when the format is not accepted. */
export function audioMimeType(name: string): string | null {
  const ext = fileExtension(name)
  return Object.hasOwn(MIME_BY_EXTENSION, ext) ? (MIME_BY_EXTENSION[ext] ?? null) : null
}

/** Format first (a wrong file is wrong whatever its size), then empty, then the size limit. */
export function checkAudioFile(file: { name: string; size: number }): AudioFileCheck {
  const mimeType = audioMimeType(file.name)
  if (mimeType === null) return { ok: false, error: 'format' }
  if (file.size <= 0) return { ok: false, error: 'empty' }
  if (file.size > MAX_AUDIO_FILE_BYTES) return { ok: false, error: 'too_large' }
  return { ok: true, mimeType }
}

/** Same bytes with the Content-Type the upload must send (a Blob's type is its Content-Type). */
export function withMimeType(file: Blob, mimeType: string): Blob {
  return file.type === mimeType ? file : new Blob([file], { type: mimeType })
}
