import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'
import { tileToneClass, type Tone } from './tones'

export interface TileProps extends ComponentProps<'div'> {
  tone?: Tone
}

/** Inner box inside a card (14px radius, tone wash, no border). */
export function Tile({ tone = 'neutral', className, ...props }: TileProps) {
  return <div data-slot="studio-tile" className={cn('rounded-tile px-3 py-2.5', tileToneClass[tone], className)} {...props} />
}
