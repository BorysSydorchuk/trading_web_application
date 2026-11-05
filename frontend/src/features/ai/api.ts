import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest } from '@/api/client'
import { healthKeys, type AiKeyStatus, type HealthResponse } from '@/api/health'

/** GET /api/ai/usage (docs/api.md "AI usage"): current Europe/Brussels month. */
export interface AiUsage {
  month: string
  cost_usd: string
  calls: number
  failed_calls: number
  unpriced_calls: number
  input_tokens: number
  output_tokens: number
  configured: boolean
  extraction_model: string
  /** AI key state (M3, an AiKeyState). Missing on an older backend. */
  key_state?: string | null
}

export const aiKeys = { usage: ['ai', 'usage'] as const }

/** POST /api/ai/check blocks up to 10 s on the server. */
const KEY_CHECK_TIMEOUT_MS = 20_000

export function useAiUsage() {
  return useQuery({
    queryKey: aiKeys.usage,
    queryFn: ({ signal }) => apiGet<AiUsage>('/ai/usage', { signal }),
    staleTime: 60_000,
  })
}

/** POST /api/ai/check: re-checks the key now; the answer updates health and usage at once, then both refetch. */
export function useCheckAiKey() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () =>
      apiRequest<AiKeyStatus>('/ai/check', { method: 'POST', timeoutMs: KEY_CHECK_TIMEOUT_MS }),
    onSuccess: async (ai) => {
      queryClient.setQueryData<HealthResponse>(healthKeys.all, (old) => (old ? { ...old, ai } : old))
      queryClient.setQueryData<AiUsage>(aiKeys.usage, (old) => (old ? { ...old, key_state: ai.state } : old))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: healthKeys.all }),
        queryClient.invalidateQueries({ queryKey: aiKeys.usage }),
      ])
    },
  })
}
