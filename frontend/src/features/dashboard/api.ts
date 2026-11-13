/** Dashboard hooks (docs/api.md "Dashboard API (PRD 6.10)"). */
import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import type { Dashboard, DigestSuggestion } from './types'

/** Same cadence as the sync status and inbox counts. */
export const DASHBOARD_POLL_MS = 30_000
/** The suggestion only changes at Friday 16:00 / month end or after a review is saved. */
export const SUGGESTION_POLL_MS = 60_000

export const dashboardKeys = {
  dashboard: ['dashboard'] as const,
  suggestion: ['digests', 'suggestion'] as const,
}

/** Errors: global toast plus the dashboard's own error block (last data stays visible). */
export function useDashboard() {
  return useQuery({
    queryKey: dashboardKeys.dashboard,
    queryFn: ({ signal }) => apiGet<Dashboard>('/dashboard', { signal }),
    refetchInterval: DASHBOARD_POLL_MS,
    staleTime: DASHBOARD_POLL_MS / 2,
  })
}

/** A secondary card: its failure is a short inline note, not a toast. */
export function useDigestSuggestion() {
  return useQuery({
    queryKey: dashboardKeys.suggestion,
    queryFn: ({ signal }) => apiGet<DigestSuggestion>('/digests/suggestion', { signal }),
    refetchInterval: SUGGESTION_POLL_MS,
    staleTime: SUGGESTION_POLL_MS / 2,
    meta: { silentError: true },
  })
}
