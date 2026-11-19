import { cn } from '@/lib/utils'

export interface LiveDotProps {
  /** Accessible name; without it the dot is decorative (the text next to it carries the meaning). */
  label?: string
  className?: string
}

/** Pulsing green dot for live data (open positions). The pulse stops under prefers-reduced-motion. */
export function LiveDot({ label, className }: LiveDotProps) {
  return (
    <span
      data-slot="studio-live-dot"
      className={cn('live-pulse inline-block size-[9px] shrink-0 rounded-full bg-profit-strong', className)}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
    />
  )
}
