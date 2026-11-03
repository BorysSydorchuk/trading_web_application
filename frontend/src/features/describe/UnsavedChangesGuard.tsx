import { useEffect, type RefObject } from 'react'
import { useBlocker } from 'react-router'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { uk } from '@/i18n/uk'

const t = uk.describe.unsaved

interface UnsavedChangesGuardProps {
  dirty: boolean
  /** Set to true right before navigating away after a successful save. */
  allowLeaveRef: RefObject<boolean>
}

/**
 * Warns before leaving with unsaved edits: in-app navigation shows a dialog, closing or
 * reloading the tab shows the browser's own prompt.
 */
export function UnsavedChangesGuard({ dirty, allowLeaveRef }: UnsavedChangesGuardProps) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty && !allowLeaveRef.current && currentLocation.pathname !== nextLocation.pathname,
  )

  useEffect(() => {
    if (!dirty) return
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault()
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [dirty])

  const open = blocker.state === 'blocked'
  return (
    <Dialog open={open} onOpenChange={(next) => !next && blocker.reset?.()}>
      <DialogContent className="sm:max-w-md" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{t.title}</DialogTitle>
          <DialogDescription>{t.description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => blocker.reset?.()}>
            {t.stay}
          </Button>
          <Button variant="destructive" onClick={() => blocker.proceed?.()}>
            {t.leave}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
