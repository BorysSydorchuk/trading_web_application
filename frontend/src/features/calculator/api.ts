import { useMutation, useQuery } from '@tanstack/react-query'
import { apiGet, apiRequest } from '@/api/client'
import type { CalculateInput, CalculateResult, MarginRequest, SymbolSpecList } from './types'

export const calculatorKeys = {
  all: ['calculator'] as const,
  specs: (accountId: number) => ['calculator', 'specs', accountId] as const,
}

/** GET /api/accounts/{id}/symbol-specs; disabled until an account is chosen. */
export function useSymbolSpecs(accountId: number | null) {
  return useQuery({
    enabled: accountId !== null,
    queryKey: calculatorKeys.specs(accountId ?? 0),
    // The form shows the load error with a retry; no second global toast.
    meta: { silentError: true },
    queryFn: ({ signal }) => apiGet<SymbolSpecList>(`/accounts/${accountId ?? 0}/symbol-specs`, { signal }),
  })
}

export function calculate(input: CalculateInput): Promise<CalculateResult> {
  return apiRequest<CalculateResult>('/calculator/calculate', { method: 'POST', body: input })
}

/** Errors are shown by the form (inline, plus its own toast for unexpected ones), not the global toast. */
export function useCalculate() {
  return useMutation({ mutationFn: calculate, meta: { silentError: true } })
}

/** POST /api/calculator/margin-requests (202): same body as calculate. */
export function createMarginRequest(input: CalculateInput, signal?: AbortSignal): Promise<MarginRequest> {
  return apiRequest<MarginRequest>('/calculator/margin-requests', { method: 'POST', body: input, signal })
}

export function getMarginRequest(id: number, signal?: AbortSignal): Promise<MarginRequest> {
  return apiGet<MarginRequest>(`/calculator/margin-requests/${id}`, { signal })
}
