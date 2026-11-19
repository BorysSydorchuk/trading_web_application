import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

type CardElement = 'section' | 'article' | 'div'

export interface CardProps extends ComponentProps<'div'> {
  /** Rendered element (default `section`). */
  as?: CardElement
  /** Hover lift: translateY(-3px) + soft shadow, 180 ms; off under prefers-reduced-motion. */
  lift?: boolean
  /** `hero`: the green-lavender-peach gradient used by the Home P&L card. */
  variant?: 'surface' | 'hero'
}

/** «Студія» card: 20px radius, white surface, hairline border. */
export function Card({ as: Element = 'section', lift = false, variant = 'surface', className, ...props }: CardProps) {
  return (
    <Element
      data-slot="studio-card"
      className={cn(
        'rounded-card border p-5 text-card-foreground',
        variant === 'hero' ? 'border-line bg-(image:--tj-hero-gradient)' : 'border-line bg-card',
        lift && 'lift',
        className,
      )}
      {...props}
    />
  )
}
