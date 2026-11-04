/** `renderWithProviders`: the app providers for component tests (query client, data router, toaster). */
import type { ReactElement, ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { Toaster } from '@/components/ui/sonner'

export interface TestRoute {
  path: string
  element: ReactNode
}

export interface RenderOptions {
  /** Route pattern the element is mounted on (e.g. `/trades/:id/describe`). */
  path?: string
  /** Start URL (defaults to `path`). */
  url?: string
  /** Other pages the test navigates to (e.g. `/inbox`). */
  routes?: readonly TestRoute[]
}

/** No retries, so an error response shows its error state at once. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
}

/**
 * Renders `ui` inside a memory data router (so `useBlocker` works) with a fresh query client
 * and the toaster. Returns the render result plus `user`, `router` and `queryClient`.
 */
export function renderWithProviders(ui: ReactElement, options: RenderOptions = {}) {
  const { path = '/', url = path, routes = [] } = options
  const queryClient = createTestQueryClient()
  const router = createMemoryRouter([{ path, element: ui }, ...routes], { initialEntries: [url] })
  const user = userEvent.setup()
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  )
  return { ...result, user, router, queryClient }
}
