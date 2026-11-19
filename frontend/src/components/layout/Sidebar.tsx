import { useCallback } from 'react'
import { NavLink, useNavigate } from 'react-router'
import { navItems } from '@/app/nav'
import { biasReminderCount, useBiasStatus } from '@/features/bias/api'
import { pendingCount, useInboxCounts, type InboxCounts } from '@/features/inbox/api'
import { useNewTradeNotifications } from '@/features/inbox/notifications'
import { useRefreshTradesOnInboxChange } from '@/features/trades/api'
import { Pill } from '@/components/studio/Pill'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

const INBOX_PATH = '/inbox'
/** Count badges: loss-soft pill (Pill tone="loss"), pushed to the right edge of the nav item. */
const BADGE_CLASS = 'ml-auto px-2 py-px leading-4 font-bold'

export function Sidebar() {
  const { data: counts } = useInboxCounts()
  const bias = useBiasStatus()
  const reminders = !bias.isError && bias.data ? biasReminderCount(bias.data) : 0
  const navigate = useNavigate()
  const openInbox = useCallback(() => void navigate(INBOX_PATH), [navigate])
  useNewTradeNotifications(counts ? pendingCount(counts) : undefined, openInbox)
  useRefreshTradesOnInboxChange(counts)

  return (
    <aside className="flex w-[236px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar px-3.5 pt-6 text-sidebar-foreground">
      <div className="flex items-center gap-3 px-2 pb-7">
        <span
          aria-hidden
          className="flex size-[34px] shrink-0 items-center justify-center rounded-[11px] bg-(image:--tj-mark-gradient) font-display text-sm font-extrabold text-ink"
        >
          {uk.app.shortName}
        </span>
        <span className="truncate font-display text-[15px] font-extrabold">{uk.app.name}</span>
      </div>
      <nav aria-label={uk.nav.label} className="flex flex-1 flex-col gap-1">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              cn(
                'flex h-10 items-center gap-2.5 rounded-xl px-3 text-sm transition-colors motion-reduce:transition-none',
                'hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground',
                'focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
                isActive
                  ? 'bg-sidebar-accent font-semibold text-sidebar-accent-foreground shadow-soft'
                  : 'text-ink-muted',
              )
            }
          >
            <Icon className="size-4 shrink-0 opacity-80" aria-hidden />
            <span className="truncate">{label}</span>
            {to === INBOX_PATH && counts && <InboxBadge counts={counts} />}
            {to === '/bias' && reminders > 0 && (
              <Pill tone="loss" mono aria-label={uk.bias.status.badge(reminders)} title={uk.bias.status.badge(reminders)} className={BADGE_CLASS}>
                {reminders}
              </Pill>
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
    <Pill
      tone="loss"
      mono
      title={tooltip}
      aria-label={counts.draft > 0 ? `${label}, ${uk.inbox.drafts(counts.draft)}` : label}
      className={BADGE_CLASS}
    >
      {pending}
    </Pill>
  )
}
