import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'
import { showErrorToast } from './errors'

/** Per-query/mutation options read by the global error handler. */
export interface AppQueryMeta extends Record<string, unknown> {
  /** Do not show the global error toast (the component renders the error itself). */
  silentError?: boolean
}

declare module '@tanstack/react-query' {
  interface Register {
    queryMeta: AppQueryMeta
    mutationMeta: AppQueryMeta
  }
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (query.meta?.silentError) return
        showErrorToast(error)
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        if (mutation.meta?.silentError) return
        showErrorToast(error)
      },
    }),
    defaultOptions: {
      queries: {
        retry: 1,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: 0,
      },
    },
  })
}
