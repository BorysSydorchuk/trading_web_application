/** M8-13: the Claude models the owner can choose (docs/api.md "M8-13"). */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest } from '@/api/client'

export const CALL_TYPES = ['trade_extraction', 'bias_extraction', 'digest_summary'] as const
export type CallType = (typeof CALL_TYPES)[number]

export interface AiModel {
  id: string
  label: string
  /** Approximate USD of one call, per call type (decimal strings). */
  approx_usd: Record<CallType, string>
}

export interface AiModels {
  models: AiModel[]
  defaults: Record<CallType, string>
}

export const aiModelKeys = { models: ['ai', 'models'] as const }

export function useAiModels() {
  return useQuery({
    queryKey: aiModelKeys.models,
    queryFn: ({ signal }) => apiGet<AiModels>('/ai/models', { signal }),
    staleTime: 60_000,
    meta: { silentError: true },
  })
}

export function useSetAiDefaults() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (change: Partial<Record<CallType, string>>) =>
      apiRequest<AiModels>('/ai/models/defaults', { method: 'PUT', body: change }),
    meta: { silentError: true },
    onSuccess: (data) => queryClient.setQueryData(aiModelKeys.models, data),
  })
}

export interface OneOffModel {
  models: readonly AiModel[]
  callType: CallType
  /** Undefined until the list is loaded: the server then uses the default. */
  model: string | undefined
  setModel: (id: string) => void
}

/** The model for the next call of ``callType``: starts at the default, changeable per call. */
export function useOneOffModel(callType: CallType): OneOffModel {
  const query = useAiModels()
  const fallback = query.data?.defaults[callType]
  const [chosen, setChosen] = useState<string | undefined>(undefined)
  const models = query.data?.models ?? []
  // The default applies until the owner picks here; a pick no longer listed falls back too.
  const valid = chosen !== undefined && models.some((m) => m.id === chosen) ? chosen : fallback
  // No list (not loaded, failed, empty): send no model, the server uses its default.
  return { models, callType, model: models.length > 0 ? valid : undefined, setModel: setChosen }
}
