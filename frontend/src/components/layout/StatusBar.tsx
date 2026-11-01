import { useHealth } from '@/api/health'
import { NotificationPrompt } from '@/features/inbox/NotificationPrompt'
import { SyncChips } from '@/features/sync/SyncChips'
import { uk } from '@/i18n/uk'
import { formatTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'

type Tone = 'ok' | 'down' | 'pending'

const dotClass: Record<Tone, string> = {
  ok: 'bg-profit',
  down: 'bg-loss',
  pending: 'bg-muted-foreground animate-pulse',
}

export function StatusBar() {
  const { data, isPending, isError, dataUpdatedAt, errorUpdatedAt } = useHealth()

  let tone: Tone
  let text: string
  if (isError) {
    // Any failure to get a health answer means the API itself is unreachable:
    // a reachable API always returns 200 (docs/api.md).
    tone = 'down'
    text = uk.statusBar.serverDown
  } else if (isPending) {
    tone = 'pending'
    text = uk.statusBar.checking
  } else if (data.status === 'ok') {
    tone = 'ok'
    text = uk.statusBar.ok
  } else {
    tone = 'down'
    text = uk.statusBar.dbDown
  }

  const lastCheckedAt = Math.max(dataUpdatedAt, errorUpdatedAt)
  const version = !isError && data ? data.version : null

  return (
    <footer
      aria-label={uk.statusBar.label}
      className="flex h-7 shrink-0 items-center gap-4 border-t border-sidebar-border bg-sidebar px-3 text-xs text-muted-foreground"
    >
      {/* Only the server/DB state is announced; sync chips and the clock would be noise every poll. */}
      <span role="status" aria-live="polite" className="flex shrink-0 items-center gap-2">
        <span className={cn('size-2 rounded-full', dotClass[tone])} aria-hidden />
        <span className={cn(tone === 'down' && 'text-loss')}>{text}</span>
      </span>
      <SyncChips />
      <span className="ml-auto flex shrink-0 items-center gap-4">
        <NotificationPrompt />
        {version !== null && (
          <span>
            {uk.statusBar.version} <span className="num">{version}</span>
          </span>
        )}
        {lastCheckedAt > 0 && (
          <span>
            {uk.statusBar.lastCheck}
            {': '}
            <span className="num">{formatTimeBrussels(lastCheckedAt)}</span>
          </span>
        )}
      </span>
    </footer>
  )
}
