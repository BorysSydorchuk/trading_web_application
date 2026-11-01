import { useEffect, useRef } from 'react'
import { uk } from '@/i18n/uk'

const PROMPT_DISMISSED_KEY = 'tj.notificationsPromptDismissed'

export function notificationsSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window
}

export function isPromptDismissed(): boolean {
  try {
    return window.localStorage.getItem(PROMPT_DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

export function rememberPromptDismissed(): void {
  try {
    window.localStorage.setItem(PROMPT_DISMISSED_KEY, '1')
  } catch {
    // Storage unavailable (private mode, quota): the prompt just comes back next time.
  }
}

/**
 * Shows a browser notification when the number of trades waiting for the user grows
 * between two polls. Never fires on the first value (page load) or without permission.
 */
export function useNewTradeNotifications(count: number | undefined, onOpen: () => void): void {
  const previous = useRef<number | null>(null)
  const onOpenRef = useRef(onOpen)

  useEffect(() => {
    onOpenRef.current = onOpen
  }, [onOpen])

  useEffect(() => {
    if (count === undefined) return
    const before = previous.current
    previous.current = count
    if (before === null || count <= before) return
    if (!notificationsSupported() || Notification.permission !== 'granted') return
    try {
      const notification = new Notification(uk.notifications.title, {
        body: uk.notifications.body(count),
        tag: 'tj-inbox',
      })
      notification.onclick = () => {
        window.focus()
        onOpenRef.current()
        notification.close()
      }
    } catch (error) {
      // Some browsers only allow notifications from a service worker; the badge still updates.
      console.error(error)
    }
  }, [count])
}
