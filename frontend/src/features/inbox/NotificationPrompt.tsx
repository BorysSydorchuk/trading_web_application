import { useState, useSyncExternalStore } from 'react'
import { Bell, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import {
  isPromptVisible,
  rememberPromptDismissed,
  requestNotificationPermission,
  subscribePrompt,
} from './notifications'

const n = uk.notifications

/**
 * Opt-in for browser notifications. Permission is requested only on click, never on page load.
 * Hidden once permission is decided or the prompt is dismissed (all instances update together).
 */
export function NotificationPrompt({ variant = 'statusBar' }: { variant?: 'statusBar' | 'inline' }) {
  const visible = useSyncExternalStore(subscribePrompt, isPromptVisible, () => false)
  const [requesting, setRequesting] = useState(false)

  if (!visible) return null

  async function enable() {
    setRequesting(true)
    await requestNotificationPermission()
    setRequesting(false)
  }

  if (variant === 'inline') {
    return (
      <div className="flex items-center gap-3 rounded-lg border bg-muted/30 px-4 py-2.5 text-xs text-muted-foreground">
        <Bell className="size-4 shrink-0" aria-hidden />
        <p className="flex-1">{n.enableHint}</p>
        <Button size="sm" variant="outline" onClick={() => void enable()} disabled={requesting}>
          {n.enable}
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-7"
          onClick={rememberPromptDismissed}
          aria-label={n.dismiss}
          title={n.dismiss}
        >
          <X aria-hidden />
        </Button>
      </div>
    )
  }

  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => void enable()}
        disabled={requesting}
        title={n.enableHint}
        className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
      >
        <Bell className="size-3" aria-hidden />
        {n.enable}
      </button>
      <button
        type="button"
        onClick={rememberPromptDismissed}
        aria-label={n.dismiss}
        title={n.dismiss}
        className="rounded p-0.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <X className="size-3" aria-hidden />
      </button>
    </span>
  )
}
