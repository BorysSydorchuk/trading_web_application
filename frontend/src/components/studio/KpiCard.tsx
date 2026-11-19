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
  /** Pressed state: the metric is shown on the main chart. */
  selected?: boolean
  onClick?: () => void
  /** Sparkline (decorative SVG, aria-hidden) under the value. */
  sparkline?: ReactNode
  className?: string
}

/** Clickable KPI card: a toggle button (aria-pressed) with a tone-coloured ring when selected. */
export function KpiCard({ label, value, hint, tone = 'neutral', selected = false, onClick, sparkline, className }: KpiCardProps) {
  const toneClass = kpiToneClass[tone]
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      data-slot="studio-kpi"
      data-tone={tone}
      className={cn(
        'lift flex w-full cursor-pointer flex-col gap-1.5 rounded-[18px] text-left outline-none',
        'focus-visible:ring-[3px] focus-visible:ring-ring/60',
        toneClass.card,
        // The 2px ring replaces the 1px border; padding shrinks by 1px so the content does not move.
        selected ? cn('border-2 px-[17px] py-[15px]', toneClass.ring) : 'border border-line px-[18px] py-4',
        className,
      )}
    >
      <span className="flex w-full items-center justify-between gap-2">
        <span className="text-[13px] text-ink-muted">{label}</span>
        {hint && (
          <span
            className={cn(
              'rounded-full px-2 py-0.5 text-[11px] font-semibold',
              selected ? pillToneClass[tone === 'neutral' ? 'accent' : tone] : 'bg-surface/80 text-ink-muted',
            )}
          >
            {hint}
          </span>
        )}
      </span>
      <span className={cn('type-kpi', toneClass.value)}>{value}</span>
      {sparkline && <span className="block h-[26px] w-full">{sparkline}</span>}
    </button>
  )
}
