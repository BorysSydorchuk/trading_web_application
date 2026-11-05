/** docs/api.md "M3 / Voice notes". */
export type AudioStatus = 'pending' | 'processing' | 'done' | 'failed'

export type TranscriptionErrorCode =
  | 'audio_unreadable'
  | 'audio_missing'
  | 'no_speech'
  | 'model_unavailable'
  | 'timeout'
  | 'transcription_failed'

export interface AudioNote {
  id: number
  trade_id: number | null
  bias_note_id: number | null
  status: AudioStatus
  /** 0.0–1.0 while processing, 1.0 when done, else null. */
  progress: number | null
  /** Decimal string, null until the worker decoded the audio. */
  duration_seconds: string | null
  mime_type: string
  transcript: string | null
  /** Only when failed; unknown codes fall back to `transcription_failed`. */
  error_code: string | null
  created_at: string
  transcribed_at: string | null
  file_url: string
}
