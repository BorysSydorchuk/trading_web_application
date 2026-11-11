import { TriangleAlert } from 'lucide-react'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'
import { formatRate, formatTickValue } from './format'
import type { ConversionInfo } from './types'

const t = uk.calculator.result

interface ConversionNoteProps {
  conversion: ConversionInfo
  /** Home panel: rate line and stale warning only. */
  compact?: boolean
}

/** M5-09: the FX rate behind the loss per tick of a cross-currency symbol (docs/api.md). */
export function ConversionNote({ conversion, compact }: ConversionNoteProps) {
  const rateLine = t.conversionRate(
    conversion.pair,
    formatRate(conversion.rate),
    conversion.side,
    formatDateTimeBrussels(conversion.rate_at),
  )
  const showMt5 = !compact && conversion.source === 'mt5_check' && conversion.mt5_loss_per_tick !== null
  return (
    <div className="flex flex-col gap-1 text-xs">
      <p className="num text-muted-foreground">{rateLine}</p>
      {conversion.stale && (
        <p className="flex items-center gap-1.5 text-amber-400">
          <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
          {t.conversionStale}
        </p>
      )}
      {showMt5 && (
        <p className="num text-muted-foreground">
          {t.conversionMt5Check(formatTickValue(conversion.mt5_loss_per_tick), formatTickValue(conversion.rate_loss_per_tick))}
        </p>
      )}
    </div>
  )
}
