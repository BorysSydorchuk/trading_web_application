import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'

/** docs/api.md `GET /api/inbox/counts`. */
export interface InboxCounts {
  needs_sl: number
  needs_description: number
  draft: number
}

export const INBOX_POLL_MS = 30_000

export const inboxKeys = {
  counts: ['inbox', 'counts'] as const,
}

export function useInboxCounts() {
  return useQuery({
    queryKey: inboxKeys.counts,
    queryFn: ({ signal }) => apiGet<InboxCounts>('/inbox/counts', { signal, timeoutMs: 5_000 }),
    refetchInterval: INBOX_POLL_MS,
    refetchIntervalInBackground: true,
    retry: false,
    meta: { silentError: true },
  })
}

/** Trades that wait for the user: missing initial SL or missing description. */
export function pendingCount(counts: InboxCounts): number {
  return counts.needs_sl + counts.needs_description
}
