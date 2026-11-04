import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest, isApiError } from '@/api/client'
import { tradeKeys } from '@/features/trades/api'
import { isActive, POLL_INTERVAL_MS } from './notesModel'
import type { AudioNote } from './types'

/** Up to 25 MB over localhost; leave room for a slow disk. */
const UPLOAD_TIMEOUT_MS = 60_000

export const audioKeys = {
  all: ['audio'] as const,
  note: (id: number) => ['audio', id] as const,
}

/**
 * The notes with these ids, each polled about every second while pending/processing.
 * `initial` (e.g. TradeDetail.audio_notes) seeds the cache so nothing is fetched for finished notes.
 */
export function useAudioNotes(ids: readonly number[], initial: readonly AudioNote[]) {
  const initialById = new Map(initial.map((note) => [note.id, note]))
  return useQueries({
    queries: ids.map((id) => ({
      queryKey: audioKeys.note(id),
      queryFn: ({ signal }: { signal: AbortSignal }) => apiGet<AudioNote>(`/audio/${id}`, { signal }),
      initialData: initialById.get(id),
      // Polling (refetchInterval) drives updates; a known note is never refetched on mount.
      staleTime: Infinity,
      refetchInterval: (query: { state: { data: AudioNote | undefined } }) =>
        isActive(query.state.data) ? POLL_INTERVAL_MS : false,
      // A failed poll is shown on the row and retried by the next tick, not toasted every second.
      meta: { silentError: true },
      retry: false,
    })),
  })
}

/** POST /api/trades/{id}/audio: the recording as the raw body (docs/api.md). */
export function useUploadTradeAudio(tradeId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (blob: Blob) =>
      apiRequest<AudioNote>(`/trades/${tradeId}/audio`, {
        method: 'POST',
        rawBody: blob,
        timeoutMs: UPLOAD_TIMEOUT_MS,
      }),
    onSuccess: (note) => {
      queryClient.setQueryData(audioKeys.note(note.id), note)
      // TradeDetail.audio_notes now lists it (seen when the page is opened again).
      return queryClient.invalidateQueries({ queryKey: tradeKeys.detail(tradeId) })
    },
  })
}

/** POST /api/audio/{id}/retry: a failed note goes back to the queue. */
export function useRetryAudio() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiRequest<AudioNote>(`/audio/${id}/retry`, { method: 'POST' }),
    onSuccess: (note) => queryClient.setQueryData(audioKeys.note(note.id), note),
    onError: (error, id) => {
      // 409 audio_not_failed: the note moved on elsewhere; show its real state.
      if (isApiError(error) && (error.code === 'audio_not_failed' || error.status === 404)) {
        void queryClient.invalidateQueries({ queryKey: audioKeys.note(id) })
      }
    },
  })
}
