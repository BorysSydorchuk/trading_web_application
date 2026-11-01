import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest, isApiError } from '@/api/client'
import type { Account, AccountInput, AccountList } from './types'

export const accountKeys = {
  all: ['accounts'] as const,
  list: (includeArchived: boolean) => ['accounts', 'list', { includeArchived }] as const,
  /** Shared key of the create/update mutations (lets the form dialog know a save is running). */
  save: ['accounts', 'save'] as const,
}

export function useAccounts(includeArchived: boolean, options: { enabled?: boolean } = {}) {
  return useQuery({
    enabled: options.enabled ?? true,
    queryKey: accountKeys.list(includeArchived),
    queryFn: ({ signal }) =>
      apiGet<AccountList>('/accounts', { signal, query: { include_archived: includeArchived } }),
    // Keep the previous table on screen while toggling "show archived".
    placeholderData: (previous) => previous,
  })
}

export function useCreateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: accountKeys.save,
    mutationFn: (input: AccountInput) =>
      apiRequest<Account>('/accounts', { method: 'POST', body: input }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: accountKeys.all }),
  })
}

export function useUpdateAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: accountKeys.save,
    mutationFn: ({ id, patch }: { id: number; patch: Partial<AccountInput> }) =>
      apiRequest<Account>(`/accounts/${id}`, { method: 'PATCH', body: patch }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: accountKeys.all }),
  })
}

/** `deleted` = row removed; `archived` = account had trades and got status "archived"; `unknown` = could not tell. */
export type DeleteOutcome = 'deleted' | 'archived' | 'unknown'

export function useDeleteAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: number): Promise<DeleteOutcome> => {
      await apiRequest<unknown>(`/accounts/${id}`, { method: 'DELETE' })
      // DELETE answers 204 in both cases; a follow-up GET tells which one happened.
      try {
        await apiGet<Account>(`/accounts/${id}`)
        return 'archived'
      } catch (error) {
        return isApiError(error) && error.code === 'not_found' ? 'deleted' : 'unknown'
      }
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: accountKeys.all }),
  })
}
