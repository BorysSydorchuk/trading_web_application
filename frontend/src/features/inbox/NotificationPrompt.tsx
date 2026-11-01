import { useState } from 'react'
import { Bell, X } from 'lucide-react'
import { uk } from '@/i18n/uk'
import { isPromptDismissed, notificationsSupported, rememberPromptDismissed } from './notifications'

/**
 * Small opt-in for browser notifications. Permission is requested only on click,
 * never on page load. Hidden once permission is decided or the prompt is dismissed.
 */
export function NotificationPrompt() {
  const [visible, setVisible] = useState(
    () => notificationsSupported() && Notification.permission === 'default' && !isPromptDismissed(),
  )
  const [requesting, setRequesting] = useState(false)

  if (!visible) return null

  async function enable() {
    setRequesting(true)
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'default') setVisible(false)
    } catch (error) {
      console.error(error)
    } finally {
      setRequesting(false)
    }
  }

  function dismiss() {
    rememberPromptDismissed()
    setVisible(false)
  }

  return (
    <span className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => void enable()}
        disabled={requesting}
        title={uk.notifications.enableHint}
        className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none disabled:opacity-50"
      >
        <Bell className="size-3" aria-hidden />
        {uk.notifications.enable}
      </button>
      <button
        type="button"
        onClick={dismiss}
        aria-label={uk.notifications.dismiss}
        title={uk.notifications.dismiss}
        className="rounded p-0.5 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <X className="size-3" aria-hidden />
      </button>
    </span>
  )
}
