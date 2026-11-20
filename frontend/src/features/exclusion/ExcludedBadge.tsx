import { EyeOff } from 'lucide-react'
import { Pill } from '@/components/studio/Pill'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

const t = uk.exclusion

/**
 * M8-01 «виключено» badge; the reason shows on hover and to screen readers. `compact` (Journal
 * table, M8-10c) shows only an icon; the word stays in the DOM for screen readers.
 */
export function ExcludedBadge({ reason, className, compact = false }: { reason: string | null; className?: string; compact?: boolean }) {
  const title = t.badgeTitle(reason ?? t.noReason)
  if (compact) {
    return (
      <Pill tone="neutral" title={title} className={cn('px-1.5', className)}>
        <EyeOff className="size-3.5" aria-hidden />
        <span title={title} className="sr-only">
          {t.badge}
        </span>
      </Pill>
    )
  }
  return (
    <Pill tone="neutral" title={title} aria-label={title} className={className}>
      {t.badge}
    </Pill>
  )
}
