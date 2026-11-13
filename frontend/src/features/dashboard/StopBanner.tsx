import { OctagonAlert } from 'lucide-react'
import { uk } from '@/i18n/uk'
import type { Dashboard } from './types'

const d = uk.dashboard

/** Red, prominent stop banner (PRD 6.9): some account hit its daily / weekly stop. */
export function StopBanner({ stop }: { stop: Dashboard['stop'] }) {
  if (!stop.today && !stop.week) return null
  return (
    <div role="alert" className="flex items-start gap-3 rounded-lg border-2 border-loss bg-loss/15 px-4 py-3 text-loss">
      <OctagonAlert className="mt-0.5 size-6 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        {stop.today && <p className="text-lg font-bold tracking-wide">{d.stopToday}</p>}
        {stop.week && <p className="text-lg font-bold tracking-wide">{d.stopWeek}</p>}
        <p className="text-sm text-foreground">{d.stopHint}</p>
      </div>
    </div>
  )
}
