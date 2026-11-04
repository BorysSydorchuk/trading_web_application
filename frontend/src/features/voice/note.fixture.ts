/** Test fixture: an AudioNote in the GET /api/audio/{id} shape (docs/api.md M3). Tests only. */
import type { AudioNote } from './types'

export function fixtureNote(overrides: Partial<AudioNote> = {}): AudioNote {
  const id = overrides.id ?? 5
  return {
    id,
    trade_id: 7,
    bias_entry_id: null,
    status: 'pending',
    progress: null,
    duration_seconds: null,
    mime_type: 'audio/webm',
    transcript: null,
    error_code: null,
    created_at: '2026-11-04T09:10:00Z',
    transcribed_at: null,
    file_url: `/api/audio/${id}/file`,
    ...overrides,
  }
}
