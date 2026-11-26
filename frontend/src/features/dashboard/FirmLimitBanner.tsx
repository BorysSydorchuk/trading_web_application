import { ShieldAlert } from 'lucide-react'
import { uk } from '@/i18n/uk'
import type { Dashboard } from './types'

const f = uk.dashboard.firmBanner

/** Critical firm-limit banner: solid red, above the personal StopBanner (account loss risk, PM 2026-11-26). */
export function FirmLimitBanner({ stop }: { stop: Dashboard['stop'] }) {
  const day = stop.firm_day === true
  const maxLoss = stop.firm_max_loss === true
  if (!day && !maxLoss) return null
  return (
    <div
      role="alert"
      data-testid="firm-limit-banner"
      className="flex items-start gap-3 rounded-lg border-2 border-loss bg-loss px-4 py-3 text-loss-wash shadow-md"
    >
      <ShieldAlert className="mt-0.5 size-6 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        {day && <p className="text-lg font-bold tracking-wide">{f.day}</p>}
        {maxLoss && <p className="text-lg font-bold tracking-wide">{f.maxLoss}</p>}
        <p className="text-sm">{f.hint}</p>
      </div>
    </div>
  )
}
