import { useEffect, useRef } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest } from '@/api/client'
import { inboxKeys, type InboxCounts } from '@/features/inbox/api'
import type { JournalFieldList, TradeDetail, TradeList, TradeQuery } from './types'

export const tradeKeys = {
  all: ['trades'] as const,
  list: (query: TradeQuery) => ['trades', 'list', query] as const,
  detail: (id: number) => ['trades', 'detail', id] as const,
  symbols: ['trades', 'symbols'] as const,
}

export function useTrades(query: TradeQuery, options: { refetchInterval?: number } = {}) {
  return useQuery({
    refetchInterval: options.refetchInterval,
    queryKey: tradeKeys.list(query),
    queryFn: ({ signal }) =>
      apiGet<TradeList>('/trades', {
        signal,
        query: {
          account_id: query.account_id,
          symbol: query.symbol,
          status: query.status,
          from: query.from,
          to: query.to,
          missing_new_fields: query.missing_new_fields,
          missing_r: query.missing_r,
          sort: query.sort,
          order: query.order,
          limit: query.limit,
          offset: query.offset,
        },
      }),
    // Keep the current page visible while the next filter/sort/page loads.
    placeholderData: keepPreviousData,
  })
}

export function useTrade(id: number | null) {
  return useQuery({
    queryKey: tradeKeys.detail(id ?? 0),
    queryFn: ({ signal }) => apiGet<TradeDetail>(`/trades/${id}`, { signal }),
    enabled: id !== null,
  })
}

export function useTradeSymbols() {
  return useQuery({
    queryKey: tradeKeys.symbols,
    queryFn: ({ signal }) => apiGet<{ items: string[] }>('/trades/symbols', { signal }),
    staleTime: 5 * 60_000,
  })
}

export function useSetInitialSl() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, initialSl }: { id: number; initialSl: string }) =>
      apiRequest<TradeDetail>(`/trades/${id}`, { method: 'PATCH', body: { initial_sl: initialSl } }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: tradeKeys.all }),
        queryClient.invalidateQueries({ queryKey: inboxKeys.counts }),
      ]),
  })
}

/**
 * When the polled inbox counts change (a new trade synced, an SL set elsewhere), refresh every
 * trades query so the inbox list and the journal show what the badge already announces.
 */
export function useRefreshTradesOnInboxChange(counts: InboxCounts | undefined): void {
  const queryClient = useQueryClient()
  const previous = useRef<string | null>(null)
  const key = counts ? `${counts.needs_sl}/${counts.needs_description}/${counts.draft}` : null

  useEffect(() => {
    if (key === null) return
    const before = previous.current
    previous.current = key
    if (before !== null && before !== key) void queryClient.invalidateQueries({ queryKey: tradeKeys.all })
  }, [key, queryClient])
}

export const journalFieldKeys = { all: ['journal-fields'] as const }

/** Field definitions from config/journal_fields.yaml. Labels fall back to uk.ts if this fails. */
export function useJournalFields() {
  return useQuery({
    queryKey: journalFieldKeys.all,
    queryFn: ({ signal }) => apiGet<JournalFieldList>('/journal-fields', { signal }),
    staleTime: 5 * 60_000,
    retry: false,
    meta: { silentError: true },
  })
}
