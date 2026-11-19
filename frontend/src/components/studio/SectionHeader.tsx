import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface SectionHeaderProps {
  title: string
  /** Heading level (default 2). */
  level?: 2 | 3
  /** id on the heading, for `aria-labelledby` on the section. */
  id?: string
  /** Pills, badges or a LiveDot shown right after the title. */
  children?: ReactNode
  /** Right-aligned actions (buttons, segmented control). */
  actions?: ReactNode
  className?: string
}

/** Section title (Manrope 800, 20px) with optional inline badges and right-side actions. */
export function SectionHeader({ title, level = 2, id, children, actions, className }: SectionHeaderProps) {
  const Heading = level === 2 ? 'h2' : 'h3'
  return (
    <div data-slot="studio-section-header" className={cn('flex flex-wrap items-center gap-3', className)}>
      <Heading id={id} className="type-section-title m-0 text-ink">
        {title}
      </Heading>
      {children}
      {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
