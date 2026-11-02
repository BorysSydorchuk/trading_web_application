import { createBrowserRouter } from 'react-router'
import { RouteErrorFallback } from '@/components/ErrorBoundary'
import { AppLayout } from '@/components/layout/AppLayout'
import { PageLoading } from '@/components/PageLoading'
import { NotFoundPage } from '@/pages/NotFoundPage'

// Route-level code splitting: each page is its own chunk, loaded by the router on navigation
// (the current page stays on screen until the next one is ready).
export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <RouteErrorFallback />,
    hydrateFallbackElement: <PageLoading />,
    children: [
      {
        // Page crashes render inside the layout, so sidebar and status bar stay usable.
        errorElement: <RouteErrorFallback />,
        children: [
          {
            index: true,
            lazy: async () => ({ Component: (await import('@/pages/HomePage')).HomePage }),
          },
          {
            path: 'inbox',
            lazy: async () => ({ Component: (await import('@/pages/InboxPage')).InboxPage }),
          },
          {
            path: 'journal',
            lazy: async () => ({ Component: (await import('@/pages/JournalPage')).JournalPage }),
          },
          {
            path: 'bias',
            lazy: async () => ({ Component: (await import('@/pages/BiasPage')).BiasPage }),
          },
          {
            path: 'digests',
            lazy: async () => ({ Component: (await import('@/pages/DigestsPage')).DigestsPage }),
          },
          {
            path: 'calculator',
            lazy: async () => ({ Component: (await import('@/pages/CalculatorPage')).CalculatorPage }),
          },
          {
            path: 'settings',
            lazy: async () => ({ Component: (await import('@/pages/SettingsPage')).SettingsPage }),
          },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
