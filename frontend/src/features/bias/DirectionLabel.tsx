import { ArrowDownRight, ArrowRight, ArrowUpRight, Ban } from 'lucide-react'
import { uk } from '@/i18n/uk'
import type { BiasDirection } from './types'

const ICONS = {
  bullish: ArrowUpRight,
  bearish: ArrowDownRight,
  neutral: ArrowRight,
  no_trade: Ban,
} as const

/** Direction as arrow + word in the neutral text colour (green/red stay for P&L). */
export function DirectionLabel({ direction }: { direction: BiasDirection }) {
  const Icon = ICONS[direction]
  return (
    <span className="inline-flex items-center gap-1 text-foreground">
      <Icon className="size-3.5 text-muted-foreground" aria-hidden />
      {uk.bias.directions[direction]}
    </span>
  )
}
