import { useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, apiRequest, isApiError } from '@/api/client'
import { aiKeys } from '@/features/ai/api'
import { inboxKeys } from '@/features/inbox/api'
import { tradeKeys } from '@/features/trades/api'
import type { TradeDetail } from '@/features/trades/types'
import type { ExtractResult, JournalInput } from './types'

/** The server keeps extraction (incl. one fallback attempt) within 30 s; leave room for the network. */
const EXTRACT_TIMEOUT_MS = 45_000

/** The trade changed status under the form: reload it so the page shows the SL form / open notice. */
const STALE_STATUS_CODES = new Set(['needs_sl', 'trade_open'])

function refreshOnStaleStatus(queryClient: QueryClient, tradeId: number, error: unknown) {
  if (isApiError(error) && STALE_STATUS_CODES.has(error.code)) {
    void queryClient.invalidateQueries({ queryKey: tradeKeys.detail(tradeId) })
  }
}

export function useSaveJournal(tradeId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: JournalInput) =>
      apiRequest<TradeDetail>(`/trades/${tradeId}/journal`, { method: 'PUT', body: input }),
    onSuccess: (trade) => {
      queryClient.setQueryData(tradeKeys.detail(tradeId), trade)
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: tradeKeys.all }),
        queryClient.invalidateQueries({ queryKey: inboxKeys.counts }),
      ])
    },
    onError: (error) => refreshOnStaleStatus(queryClient, tradeId, error),
  })
}

/** A client-side timeout is shown as the AI timeout, not as "server unavailable". */
async function extract(tradeId: number, text: string): Promise<ExtractResult> {
  try {
    return await apiRequest<ExtractResult>(`/trades/${tradeId}/extract`, {
      method: 'POST',
      body: { text },
      timeoutMs: EXTRACT_TIMEOUT_MS,
    })
  } catch (error) {
    if (isApiError(error) && error.code === 'timeout') {
      throw new ApiError('ai_error', error.message, 0, { kind: 'timeout' })
    }
    throw error
  }
}

export function useExtract(tradeId: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (text: string) => extract(tradeId, text),
    // Errors are shown inline next to the button (ai_not_configured is a calm note, not a red toast).
    meta: { silentError: true },
    onError: (error) => refreshOnStaleStatus(queryClient, tradeId, error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: aiKeys.usage }),
  })
}
