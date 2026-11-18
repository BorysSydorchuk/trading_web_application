import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'

const t = uk.exclusion

/** M8-01 «виключено» badge; the reason shows on hover and to screen readers. */
export function ExcludedBadge({ reason, className }: { reason: string | null; className?: string }) {
  const title = t.badgeTitle(reason ?? t.noReason)
  return (
    <span
      title={title}
      aria-label={title}
      className={cn(
        'inline-flex items-center rounded-full border border-amber-500/50 px-1.5 py-0.5 text-[11px] leading-none text-amber-600 dark:text-amber-400',
        className,
      )}
    >
      {t.badge}
    </span>
  )
}
