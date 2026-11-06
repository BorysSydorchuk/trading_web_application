import { useCallback } from 'react'
import { NavLink, useNavigate } from 'react-router'
import { navItems } from '@/app/nav'
import { biasReminderCount, useBiasStatus } from '@/features/bias/api'
import { pendingCount, useInboxCounts, type InboxCounts } from '@/features/inbox/api'
import { useNewTradeNotifications } from '@/features/inbox/notifications'
import { useRefreshTradesOnInboxChange } from '@/features/trades/api'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

const INBOX_PATH = '/inbox'

export function Sidebar() {
  const { data: counts } = useInboxCounts()
  const bias = useBiasStatus()
  const reminders = !bias.isError && bias.data ? biasReminderCount(bias.data) : 0
  const navigate = useNavigate()
  const openInbox = useCallback(() => void navigate(INBOX_PATH), [navigate])
  useNewTradeNotifications(counts ? pendingCount(counts) : undefined, openInbox)
  useRefreshTradesOnInboxChange(counts)

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
            {to === INBOX_PATH && counts && <InboxBadge counts={counts} />}
            {to === '/bias' && reminders > 0 && (
              <span aria-label={uk.bias.status.badge(reminders)} title={uk.bias.status.badge(reminders)} className="num ml-auto rounded-full bg-primary px-1.5 py-px text-xs leading-4 font-semibold text-primary-foreground">
                {reminders}
              </span>
            )}
            {to === '/bias' && bias.isError && (
              <span role="status" className="ml-auto text-xs" title={uk.bias.status.loadError} aria-label={uk.bias.status.loadError}>
                {uk.bias.status.unavailable}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

/** needs_sl + needs_description; drafts only in the tooltip. Hidden at zero. */
function InboxBadge({ counts }: { counts: InboxCounts }) {
  const pending = pendingCount(counts)
  if (pending === 0) return null
  const label = uk.inbox.badgeLabel(pending)
  const tooltip = counts.draft > 0 ? `${label}\n${uk.inbox.drafts(counts.draft)}` : label
  return (
    <span
      title={tooltip}
      aria-label={counts.draft > 0 ? `${label}, ${uk.inbox.drafts(counts.draft)}` : label}
      className="num ml-auto rounded-full bg-primary px-1.5 py-px text-xs leading-4 font-semibold text-primary-foreground"
    >
      {pending}
    </span>
  )
}
