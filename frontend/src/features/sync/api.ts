import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { accountKeys } from '@/features/accounts/api'
import type { AccountList, AccountPlatform } from '@/features/accounts/types'

/** docs/api.md "Sync status" (PRD 6.2). */
export const SYNC_STATES = ['ok', 'warning', 'error', 'running', 'never', 'stale'] as const
export type SyncState = (typeof SYNC_STATES)[number]

/** Known state, or null for a state added to the API later (rendered as a neutral chip). */
export function knownSyncState(state: string): SyncState | null {
  return (SYNC_STATES as readonly string[]).includes(state) ? (state as SyncState) : null
}

export interface SyncStatusRow {
  account_id: number
  account_name: string
  /** A SyncState; typed as string so unknown future states do not break rendering. */
  state: string
  last_attempt_utc: string | null
  last_success_utc: string | null
  error_code: string | null
  error_message: string | null
  server_offset_hours: number | null
  open_positions: number | null
}

export interface SyncStatusList {
  items: SyncStatusRow[]
}

export const SYNC_POLL_MS = 30_000

export const syncKeys = {
  status: ['sync', 'status'] as const,
}

export function useSyncStatus() {
  return useQuery({
    queryKey: syncKeys.status,
    queryFn: ({ signal }) => apiGet<SyncStatusList>('/sync/status', { signal, timeoutMs: 5_000 }),
    refetchInterval: SYNC_POLL_MS,
    refetchIntervalInBackground: true,
    retry: false,
    // The status bar renders the state itself (and hides the chips if the endpoint is missing).
    meta: { silentError: true },
  })
}

/**
 * `GET /api/sync/status` has no `platform`, so the chips join it from the accounts list.
 * Own key under `accounts`: a saved account refreshes it, and its failure stays silent
 * (the chips then just show no platform label).
 */
export function useSyncPlatforms(enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: [...accountKeys.all, 'platforms'] as const,
    queryFn: ({ signal }) =>
      apiGet<AccountList>('/accounts', { signal, timeoutMs: 5_000, query: { include_archived: true } }),
    select: (list): ReadonlyMap<number, AccountPlatform> => new Map(list.items.map((item) => [item.id, item.platform])),
    retry: false,
    meta: { silentError: true },
  })
}
