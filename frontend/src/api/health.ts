import { useQuery } from '@tanstack/react-query'
import { apiGet } from './client'

export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  time_utc: string
  db: { ok: boolean; latency_ms: number | null; error: string | null }
}

export const HEALTH_POLL_MS = 15_000

export const healthKeys = {
  all: ['health'] as const,
}

export function useHealth() {
  return useQuery({
    queryKey: healthKeys.all,
    queryFn: ({ signal }) => apiGet<HealthResponse>('/health', { signal, timeoutMs: 5_000 }),
    refetchInterval: HEALTH_POLL_MS,
    refetchIntervalInBackground: true,
    retry: false,
    // The status bar shows the state itself; no toast every 15 s.
    meta: { silentError: true },
  })
}
