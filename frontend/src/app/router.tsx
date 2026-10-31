import { createBrowserRouter } from 'react-router'
import { RouteErrorFallback } from '@/components/ErrorBoundary'
import { AppLayout } from '@/components/layout/AppLayout'
import { BiasPage } from '@/pages/BiasPage'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { DigestsPage } from '@/pages/DigestsPage'
import { HomePage } from '@/pages/HomePage'
import { InboxPage } from '@/pages/InboxPage'
import { JournalPage } from '@/pages/JournalPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { SettingsPage } from '@/pages/SettingsPage'

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <RouteErrorFallback />,
    children: [
      {
        // Page crashes render inside the layout, so sidebar and status bar stay usable.
        errorElement: <RouteErrorFallback />,
        children: [
          { index: true, element: <HomePage /> },
          { path: 'inbox', element: <InboxPage /> },
          { path: 'journal', element: <JournalPage /> },
          { path: 'bias', element: <BiasPage /> },
          { path: 'digests', element: <DigestsPage /> },
          { path: 'calculator', element: <CalculatorPage /> },
          { path: 'settings', element: <SettingsPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
    ],
  },
])
