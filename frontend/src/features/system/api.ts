import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest } from '@/api/client'

/** docs/api.md M8-12 `GET /api/system/desktop`. */
export interface DesktopState {
  /** Windows only; elsewhere the section explains it is not available. */
  supported: boolean
  autostart: boolean
  terminals_visible: boolean
}

export type DesktopChange = { autostart: boolean } | { terminals_visible: boolean }

export const systemKeys = { desktop: ['system', 'desktop'] as const }

export function useDesktopState() {
  return useQuery({
    queryKey: systemKeys.desktop,
    queryFn: ({ signal }) => apiGet<DesktopState>('/system/desktop', { signal }),
  })
}

export function useSetDesktop() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (change: DesktopChange) =>
      'autostart' in change
        ? apiRequest<DesktopState>('/system/autostart', { method: 'PUT', body: { enabled: change.autostart } })
        : apiRequest<DesktopState>('/system/terminals', { method: 'PUT', body: { visible: change.terminals_visible } }),
    meta: { silentError: true },
    onSuccess: (state) => queryClient.setQueryData(systemKeys.desktop, state),
  })
}
