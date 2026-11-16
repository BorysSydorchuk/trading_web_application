import { useLayoutEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router'
import { Sidebar } from './Sidebar'
import { StatusBar } from './StatusBar'

export function AppLayout() {
  const mainRef = useRef<HTMLElement>(null)
  const { pathname } = useLocation()

  // <main> is the only scroll container and it outlives route changes: start every page at the top.
  useLayoutEffect(() => {
    const main = mainRef.current
    if (main) {
      main.scrollTop = 0
      main.scrollLeft = 0
    }
  }, [pathname])

  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        {/* `relative`: absolutely positioned content (e.g. `.sr-only` texts) is clipped by this
            scroll container instead of stretching the document past the viewport (M8-11). */}
        <main ref={mainRef} className="relative min-w-0 flex-1 overflow-y-auto px-6 py-5">
          <Outlet />
        </main>
      </div>
      <StatusBar />
    </div>
  )
}
