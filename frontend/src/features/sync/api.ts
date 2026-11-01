import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'

/** docs/api.md "Sync status" (PRD 6.2). */
export const SYNC_STATES = ['ok', 'error', 'running', 'never', 'stale'] as const
export type SyncState = (typeof SYNC_STATES)[number]

export interface SyncStatusRow {
  account_id: number
  account_name: string
  state: SyncState
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
