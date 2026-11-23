import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiGet, apiRequest } from '@/api/client'
import { accountKeys } from '@/features/accounts/api'
import type { Account, CtraderAccountInput } from '@/features/accounts/types'
import { syncKeys } from '@/features/sync/api'
import { isSafeAuthorizeUrl, navigateToAuthorizeUrl } from './navigation'
import type { CtraderAccountList, CtraderStatus } from './types'

export const ctraderKeys = {
  all: ['ctrader'] as const,
  status: ['ctrader', 'status'] as const,
  accounts: ['ctrader', 'accounts'] as const,
}

/** Silent: Settings only hides the disconnect action; the add flow shows the error itself. */
export function useCtraderStatus() {
  return useQuery({
    queryKey: ctraderKeys.status,
    queryFn: ({ signal }) => apiGet<CtraderStatus>('/ctrader/status', { signal }),
    staleTime: 0,
    meta: { silentError: true },
  })
}

export function useCtraderAccounts(enabled: boolean) {
  return useQuery({
    enabled,
    queryKey: ctraderKeys.accounts,
    queryFn: ({ signal }) => apiGet<CtraderAccountList>('/ctrader/accounts', { signal }),
    staleTime: 0,
    retry: false,
  })
}

/** Asks for the sign-in address and leaves the app for it. */
export function useConnectCtrader() {
  return useMutation({
    mutationFn: async () => {
      const { authorize_url: url } = await apiRequest<{ authorize_url: string }>('/ctrader/connect', { method: 'POST' })
      if (!isSafeAuthorizeUrl(url)) throw new ApiError('ctrader_bad_response', 'Unsafe authorize URL', 502)
      navigateToAuthorizeUrl(url)
    },
  })
}

export function useAddCtraderAccount() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationKey: accountKeys.save,
    mutationFn: (input: CtraderAccountInput) =>
      apiRequest<Account>('/ctrader/accounts', { method: 'POST', body: input }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: accountKeys.all }),
        queryClient.invalidateQueries({ queryKey: ctraderKeys.all }),
        queryClient.invalidateQueries({ queryKey: syncKeys.status }),
      ]),
  })
}

export function useDisconnectCtrader() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => apiRequest<unknown>('/ctrader/connection', { method: 'DELETE' }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: ctraderKeys.all }),
        queryClient.invalidateQueries({ queryKey: syncKeys.status }),
      ]),
  })
}
