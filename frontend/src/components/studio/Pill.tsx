import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'
import { dotToneClass, pillToneClass, type Tone } from './tones'

export interface PillProps extends ComponentProps<'span'> {
  tone?: Tone
  /** `sm` for badges and inline tags (default), `md` for header chips. */
  size?: 'sm' | 'md'
  /** Monospace digits for numeric pills (P&L, counts). */
  mono?: boolean
  /** Leading status dot in the tone's strong shade. */
  dot?: boolean
}

const sizeClass = {
  sm: 'gap-1.5 px-2.5 py-0.5 text-xs',
  md: 'gap-2 px-3 py-1.5 text-[13px]',
} as const

/** Rounded status pill: soft background + its own text colour (never muted text on loss-soft). */
export function Pill({ tone = 'neutral', size = 'sm', mono = false, dot = false, className, children, ...props }: PillProps) {
  return (
    <span
      data-slot="studio-pill"
      data-tone={tone}
      className={cn('inline-flex items-center rounded-full font-semibold whitespace-nowrap', sizeClass[size], pillToneClass[tone], mono && 'num', className)}
      {...props}
    >
      {dot && <span className={cn('size-2 shrink-0 rounded-full', dotToneClass[tone])} aria-hidden />}
      {children}
    </span>
  )
}

/** Page header chip (session, bias, quick links): a medium pill. */
export function HeaderChip(props: Omit<PillProps, 'size'>) {
  return <Pill size="md" {...props} />
}
