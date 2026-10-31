import { Outlet } from 'react-router'
import { Sidebar } from './Sidebar'
import { StatusBar } from './StatusBar'

export function AppLayout() {
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto px-6 py-5">
          <Outlet />
        </main>
      </div>
      <StatusBar />
    </div>
  )
}
