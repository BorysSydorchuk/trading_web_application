/** Digests API hooks (docs/api.md "Digests API"). */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { apiGet, apiRequest, isApiError } from '@/api/client'
import { dashboardKeys } from '@/features/dashboard/api'
import { uk } from '@/i18n/uk'
import { showErrorToast } from '@/lib/errors'
import type { Digest, DigestKind, DigestListItem, ReviewInput } from './types'

/** Generating a snapshot reads the period and the norm window; allow more than the default 10 s. */
const GENERATE_TIMEOUT_MS = 30_000

export const digestKeys = {
  lists: ['digests', 'list'] as const,
  list: (kind: DigestKind) => ['digests', 'list', kind] as const,
  period: (kind: DigestKind, date: string) => ['digests', 'period', kind, date] as const,
}

export function useDigestList(kind: DigestKind) {
  return useQuery({
    queryKey: digestKeys.list(kind),
    queryFn: ({ signal }) => apiGet<{ items: DigestListItem[] }>('/digests', { signal, query: { kind } }),
  })
}

function generateDigest(kind: DigestKind, date: string): Promise<Digest> {
  return apiRequest<Digest>('/digests', { method: 'POST', body: { kind, date }, timeoutMs: GENERATE_TIMEOUT_MS })
}

/**
 * The digest of a period: `GET by-period`; on 404 it is created on demand (`POST`), so a virtual
 * list row or the Home suggestion opens a full digest. Errors (409 mixed_currency, 422
 * period_in_future) get the global toast and the page's inline error state.
 */
export function usePeriodDigest(kind: DigestKind, date: string) {
  const queryClient = useQueryClient()
  return useQuery({
    queryKey: digestKeys.period(kind, date),
    queryFn: async ({ signal }) => {
      try {
        return await apiGet<Digest>('/digests/by-period', { signal, query: { kind, date } })
      } catch (error) {
        if (!isApiError(error) || error.status !== 404) throw error
      }
      const created = await generateDigest(kind, date)
      void queryClient.invalidateQueries({ queryKey: digestKeys.lists })
      return created
    },
    retry: false,
  })
}

function afterWrite(queryClient: QueryClient, digest: Digest) {
  queryClient.setQueryData(digestKeys.period(digest.kind, digest.period_start), digest)
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: digestKeys.lists }),
    queryClient.invalidateQueries({ queryKey: dashboardKeys.suggestion }),
  ])
}

/** «Оновити»: POST regenerates the snapshot; review texts and ai_summary are kept by the server. */
export function useRegenerateDigest() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (digest: Digest) => generateDigest(digest.kind, digest.period_start),
    meta: { silentError: true },
    onSuccess: (digest) => {
      toast(uk.digests.page.regenerated, { id: 'digest-regenerated' })
      return afterWrite(queryClient, digest)
    },
    onError: showErrorToast,
  })
}

/** PATCH the three review texts (`""` clears a field on the server). */
export function useSaveReview(id: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ReviewInput) => apiRequest<Digest>(`/digests/${id}`, { method: 'PATCH', body: input }),
    meta: { silentError: true },
    onSuccess: (digest) => {
      toast(uk.digests.review.saved, { id: 'digest-review-saved' })
      return afterWrite(queryClient, digest)
    },
    onError: showErrorToast,
  })
}
