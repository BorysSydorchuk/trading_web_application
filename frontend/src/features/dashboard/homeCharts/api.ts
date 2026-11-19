import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'
import { DASHBOARD_POLL_MS } from '../api'

/** docs/api.md M8-14 `GET /api/dashboard/charts`: money 2 dp, percents and R 4 dp (strings). */
export interface HomeCharts {
  from: string
  to: string
  currency: string | null
  account_size: string | null
  trades: number
  equity: { time: string; cum_pnl: string; cum_pct: string | null }[]
  daily: { day: string; net_pnl: string; pct: string | null; trades: number }[]
  rolling: { time: string; n: number; win_rate: string; avg_r: string | null }[]
  rolling_window: number
}

export const homeChartKeys = {
  all: ['dashboard', 'charts'] as const,
  range: (from: string, to: string, accountId: number | null) => ['dashboard', 'charts', from, to, accountId] as const,
}

export function useHomeCharts(range: { from: string; to: string } | null, accountId: number | null) {
  return useQuery({
    queryKey: homeChartKeys.range(range?.from ?? '', range?.to ?? '', accountId),
    queryFn: ({ signal }) =>
      apiGet<HomeCharts>('/dashboard/charts', {
        signal,
        query: { from: range?.from, to: range?.to, account_id: accountId ?? undefined },
      }),
    enabled: range !== null,
    // New trades from a sync appear like the rest of Home.
    refetchInterval: DASHBOARD_POLL_MS,
    placeholderData: keepPreviousData,
    meta: { silentError: true },
  })
}
