/** M8-10b `GET /api/home` (docs/api.md "## M8-10b"). */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { DASHBOARD_POLL_MS } from '@/features/dashboard/api'
import type { HomeData } from './types'

export const homeKeys = {
  all: ['home'] as const,
  account: (accountId: number | null) => ['home', accountId] as const,
}

/** Polls like the rest of Home (30 s); errors are shown inline (no toast from a poll). */
export function useHome(accountId: number | null) {
  return useQuery({
    queryKey: homeKeys.account(accountId),
    queryFn: ({ signal }) => apiGet<HomeData>('/home', { signal, query: { account_id: accountId ?? undefined } }),
    refetchInterval: DASHBOARD_POLL_MS,
    staleTime: DASHBOARD_POLL_MS / 2,
    placeholderData: keepPreviousData,
    meta: { silentError: true },
  })
}
