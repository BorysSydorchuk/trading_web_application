/** Bias API hooks (docs/api.md "## M4"). */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, apiGet, apiRequest, isApiError } from '@/api/client'
import { aiKeys } from '@/features/ai/api'
import { tradeKeys } from '@/features/trades/api'
import { audioKeys } from '@/features/voice/api'
import type { AudioNote } from '@/features/voice/types'
import type { BiasConfig, BiasEntry, BiasExtractResult, BiasKind, BiasNote, BiasNoteInput } from './types'

/** Same budget as the trade extraction (server keeps it within 30 s). */
const EXTRACT_TIMEOUT_MS = 45_000
/** Up to 25 MB over localhost (same as the trade upload). */
const UPLOAD_TIMEOUT_MS = 60_000

export const biasKeys = {
  all: ['bias'] as const,
  config: ['bias', 'config'] as const,
  notes: ['bias', 'notes'] as const,
  lists: ['bias', 'notes', 'list'] as const,
  list: (kinds: readonly string[]) => ['bias', 'notes', 'list', [...kinds].sort()] as const,
  detail: (id: number) => ['bias', 'notes', 'detail', id] as const,
  byPeriod: (kind: string, date: string) => ['bias', 'notes', 'by-period', kind, date] as const,
  status: ['bias', 'status'] as const,
}

export function useBiasConfig() {
  return useQuery({
    queryKey: biasKeys.config,
    queryFn: ({ signal }) => apiGet<BiasConfig>('/bias/config', { signal }),
  })
}

/** Default range: the last 30 days (server side); `kinds` empty = all kinds. */
export function useBiasNotes(kinds: readonly BiasKind[]) {
  return useQuery({
    queryKey: biasKeys.list(kinds),
    queryFn: ({ signal }) => apiGet<{ items: BiasNote[] }>('/bias/notes', { signal, query: { kind: kinds } }),
  })
}

export function useBiasNote(id: number | null) {
  return useQuery({
    queryKey: biasKeys.detail(id ?? 0),
    queryFn: ({ signal }) => apiGet<BiasNote>(`/bias/notes/${id ?? 0}`, { signal }),
    enabled: id !== null,
  })
}

/** The note for kind + date, or null (404). Used to warn before a 409 on save. */
export function useBiasNoteByPeriod(kind: BiasKind, date: string, enabled: boolean) {
  return useQuery({
    queryKey: biasKeys.byPeriod(kind, date),
    queryFn: async ({ signal }) => {
      try {
        return await apiGet<BiasNote>('/bias/notes/by-period', { signal, query: { kind, date } })
      } catch (error) {
        if (isApiError(error) && error.status === 404) return null
        throw error
      }
    },
    enabled,
    // Only a hint; a failure here must not bother the user (the save reports a real clash).
    meta: { silentError: true },
    retry: false,
  })
}

/** A write changes notes, the dashboard status and the trades' bias alignment (docs/api.md M4). */
export function invalidateAfterWrite(queryClient: QueryClient, note?: BiasNote) {
  if (note) queryClient.setQueryData(biasKeys.detail(note.id), note)
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: biasKeys.lists }),
    queryClient.invalidateQueries({ queryKey: ['bias', 'notes', 'by-period'] }),
    queryClient.invalidateQueries({ queryKey: biasKeys.status }),
    queryClient.invalidateQueries({ queryKey: tradeKeys.all }),
  ])
}

export function createBiasNote(input: BiasNoteInput): Promise<BiasNote> {
  return apiRequest<BiasNote>('/bias/notes', { method: 'POST', body: input })
}

/** POST (no id yet) or PUT. Errors are shown by the editor (fields, 409 notice, toast). */
export function useSaveBiasNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: number | null; input: BiasNoteInput }) =>
      id === null ? createBiasNote(input) : apiRequest<BiasNote>(`/bias/notes/${id}`, { method: 'PUT', body: input }),
    meta: { silentError: true },
    onSuccess: (note) => invalidateAfterWrite(queryClient, note),
  })
}

export function useDeleteBiasNote() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => apiRequest<undefined>(`/bias/notes/${id}`, { method: 'DELETE' }),
    meta: { silentError: true },
    onSuccess: () => invalidateAfterWrite(queryClient),
  })
}

function replaceEntry(note: BiasNote, entry: BiasEntry): BiasNote {
  return { ...note, entries: note.entries.map((e) => (e.id === entry.id ? entry : e)) }
}

/** PATCH /api/bias/entries/{id}/result; the lists show the new mark at once. */
export function useSetBiasResult() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ entryId, wasCorrect }: { entryId: number; wasCorrect: boolean | null }) =>
      apiRequest<BiasEntry>(`/bias/entries/${entryId}/result`, { method: 'PATCH', body: { was_correct: wasCorrect } }),
    meta: { silentError: true },
    onSuccess: (entry) => {
      queryClient.setQueriesData<{ items: BiasNote[] }>({ queryKey: biasKeys.lists }, (data) =>
        data ? { items: data.items.map((note) => replaceEntry(note, entry)) } : data,
      )
      return queryClient.invalidateQueries({ queryKey: biasKeys.notes, refetchType: 'none' })
    },
  })
}

/** A client-side timeout is shown as the AI timeout, not as "server unavailable" (as on Describe). */
async function extractBias(kind: BiasKind, text: string): Promise<BiasExtractResult> {
  try {
    return await apiRequest<BiasExtractResult>('/bias/notes/extract', {
      method: 'POST',
      body: { kind, text },
      timeoutMs: EXTRACT_TIMEOUT_MS,
    })
  } catch (error) {
    if (isApiError(error) && error.code === 'timeout') {
      throw new ApiError('ai_error', error.message, 0, { kind: 'timeout' })
    }
    throw error
  }
}

export function useBiasExtract() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, text }: { kind: BiasKind; text: string }) => extractBias(kind, text),
    // Shown inline next to the button (ai_not_configured is a calm note, not a red toast).
    meta: { silentError: true },
    onSettled: () => queryClient.invalidateQueries({ queryKey: aiKeys.usage }),
  })
}

/**
 * POST /api/bias/notes/{id}/audio. `ensureNoteId` gives the note id, creating the note first
 * when it does not exist yet (DECISIONS M4-05: a new note is created with entries [] for voice).
 */
export function useUploadBiasAudio(ensureNoteId: () => Promise<number>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (blob: Blob) => {
      const id = await ensureNoteId()
      return apiRequest<AudioNote>(`/bias/notes/${id}/audio`, { method: 'POST', rawBody: blob, timeoutMs: UPLOAD_TIMEOUT_MS })
    },
    // Like the trade upload: global toast plus the kept blob with retry in the recorder area.
    onSuccess: (note) => {
      queryClient.setQueryData(audioKeys.note(note.id), note)
      if (note.bias_note_id !== null) {
        return queryClient.invalidateQueries({ queryKey: biasKeys.detail(note.bias_note_id), refetchType: 'none' })
      }
    },
  })
}
