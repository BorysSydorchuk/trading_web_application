import { NavLink } from 'react-router'
import { navItems } from '@/app/nav'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

export function Sidebar() {
  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="flex h-11 items-center gap-2 border-b border-sidebar-border px-4">
        <span className="num rounded bg-sidebar-accent px-1.5 py-0.5 text-xs font-semibold text-sidebar-accent-foreground">
          {uk.app.shortName}
        </span>
        <span className="truncate text-sm font-medium">{uk.app.name}</span>
      </div>
      <nav aria-label={uk.nav.label} className="flex flex-1 flex-col gap-0.5 p-2">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex h-8 items-center gap-2.5 rounded-md px-2.5 text-sm transition-colors',
                'hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
                'focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none',
                isActive
                  ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
                  : 'text-sidebar-foreground/75',
              )
            }
          >
            <Icon className="size-4 shrink-0 opacity-80" aria-hidden />
            <span className="truncate">{label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
