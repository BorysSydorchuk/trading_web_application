import { useEffect, useRef } from 'react'
import { uk } from '@/i18n/uk'

const PROMPT_DISMISSED_KEY = 'tj.notificationsPromptDismissed'

export function notificationsSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window
}

// In-memory copy so dismissal works for this session even if localStorage is unavailable.
let dismissedInSession = false
const promptListeners = new Set<() => void>()

function emitPromptChange(): void {
  for (const listener of promptListeners) listener()
}

/** useSyncExternalStore subscription: every prompt instance updates together. */
export function subscribePrompt(listener: () => void): () => void {
  promptListeners.add(listener)
  return () => {
    promptListeners.delete(listener)
  }
}

export function isPromptDismissed(): boolean {
  if (dismissedInSession) return true
  try {
    return window.localStorage.getItem(PROMPT_DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

/** Prompt is shown only while permission is undecided and the user did not dismiss it. */
export function isPromptVisible(): boolean {
  return notificationsSupported() && Notification.permission === 'default' && !isPromptDismissed()
}

export function rememberPromptDismissed(): void {
  dismissedInSession = true
  try {
    window.localStorage.setItem(PROMPT_DISMISSED_KEY, '1')
  } catch {
    // Storage unavailable (private mode, quota): dismissal lasts for this session only.
  }
  emitPromptChange()
}

/** Asks the browser for permission (only ever called from a click). */
export async function requestNotificationPermission(): Promise<void> {
  try {
    await Notification.requestPermission()
  } catch {
    // Permission request failed (old browser API); the prompt state is refreshed below.
  } finally {
    emitPromptChange()
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
    } catch {
      // Some browsers only allow notifications from a service worker; the badge still updates.
    }
  }, [count])
}
