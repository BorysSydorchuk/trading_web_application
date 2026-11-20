import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { kpiToneClass, pillToneClass, type KpiTone } from './tones'

export interface KpiCardProps {
  label: string
  /** Already formatted value (displayFormat, overview mode). */
  value: string
  /** Small right-top hint, e.g. "графік ↗" / "на графіку". */
  hint?: string
  tone?: KpiTone
  /** Pressed state: the metric is shown on the main chart (only with `onClick`). */
  selected?: boolean
  /** Makes the card a toggle button; without it the card is static. */
  onClick?: () => void
  /** Small muted lines under the value (context, notes). */
  caption?: ReactNode
  /** Sparkline (decorative SVG, aria-hidden) under the value. */
  sparkline?: ReactNode
  className?: string
}

/**
 * KPI card. With `onClick` it is a toggle button (aria-pressed, hover lift) with a tone-coloured ring
 * when selected; without `onClick` it is a static block (no button, no pressed state).
 */
export function KpiCard({ label, value, hint, tone = 'neutral', selected = false, onClick, caption, sparkline, className }: KpiCardProps) {
  const toneClass = kpiToneClass[tone]
  const interactive = onClick !== undefined
  const pressed = interactive && selected
  const classes = cn(
    'flex w-full flex-col gap-1.5 rounded-[18px] text-left',
    toneClass.card,
    // The 2px ring replaces the 1px border; padding shrinks by 1px so the content does not move.
    pressed ? cn('border-2 px-[17px] py-[15px]', toneClass.ring) : 'border border-line px-[18px] py-4',
    interactive && 'lift cursor-pointer outline-none focus-visible:ring-[3px] focus-visible:ring-ring',
    className,
  )
  const content = (
    <>
      <span className="flex w-full items-center justify-between gap-2">
        <span className="text-[13px] text-ink-muted">{label}</span>
        {hint && (
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[11px] font-semibold',
              pressed ? pillToneClass[tone === 'neutral' ? 'accent' : tone] : 'bg-surface/80 text-ink-muted',
            )}
          >
            {hint}
          </span>
        )}
      </span>
      <span className={cn('type-kpi', toneClass.value)}>{value}</span>
      {caption && <span className="flex flex-col text-[11px] text-ink-muted">{caption}</span>}
      {sparkline && <span className="block h-[26px] w-full">{sparkline}</span>}
    </>
  )
  if (!interactive) {
    return (
      <div data-slot="studio-kpi" data-tone={tone} className={classes}>
        {content}
      </div>
    )
  }
  return (
    <button type="button" aria-pressed={pressed} onClick={onClick} data-slot="studio-kpi" data-tone={tone} className={classes}>
      {content}
    </button>
  )
}
