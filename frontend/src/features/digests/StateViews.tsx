import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'

export function LoadingNote({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-center gap-2 text-xs text-ink-muted">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden />
      {text}
    </div>
  )
}

interface LoadErrorProps {
  text: string
  error: unknown
  onRetry: () => void
  busy: boolean
}

/** Inline error with the readable API reason (e.g. mixed_currency, period_in_future) and a retry. */
export function LoadErrorNote({ text, error, onRetry, busy }: LoadErrorProps) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 rounded-card border border-dashed border-input bg-surface px-6 py-8 text-center">
      <p>{text}</p>
      <p className="text-xs text-ink-muted">{errorText(error)}</p>
      <Button variant="outline" size="sm" onClick={onRetry} disabled={busy}>
        {busy && <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
        {uk.common.retry}
      </Button>
    </div>
  )
}
