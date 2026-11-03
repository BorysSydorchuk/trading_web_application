import { useQuery } from '@tanstack/react-query'
import { apiGet } from '@/api/client'

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
}

export const aiKeys = { usage: ['ai', 'usage'] as const }

export function useAiUsage() {
  return useQuery({
    queryKey: aiKeys.usage,
    queryFn: ({ signal }) => apiGet<AiUsage>('/ai/usage', { signal }),
    staleTime: 60_000,
  })
}
