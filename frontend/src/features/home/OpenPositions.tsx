import { useId } from 'react'
import { LiveDot } from '@/components/studio/LiveDot'
import { Pill } from '@/components/studio/Pill'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { uk } from '@/i18n/uk'
import { formatPct, formatUsd } from '@/lib/displayFormat'
import { signTone } from './heroSeries'
import { PositionCard } from './PositionCard'
import type { HomeData } from './types'

const t = uk.home.positions

/** «Відкриті позиції»: live dot, total P&L and risk pills, one card per position (API order). */
export function OpenPositions({ data }: { data: HomeData }) {
  const id = useId()
  const { open_positions: positions, open_totals: totals } = data
  const totalTone = signTone(totals.pnl)
  const live = positions.some((p) => p.current_price !== null)
  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-3">
      <SectionHeader id={`${id}-title`} title={t.title}>
        {live && <LiveDot label={t.live} />}
        {positions.length > 0 && totals.pnl !== null && (
          <Pill tone={totalTone === 'neutral' ? 'neutral' : totalTone} mono size="md" aria-label={`${t.total}: ${formatUsd(totals.pnl, 'overview', { signed: true })}`} className="py-1">
            {formatUsd(totals.pnl, 'overview', { signed: true })}
            {data.limits && ` ${data.limits.currency}`}
          </Pill>
        )}
        {positions.length > 0 && totals.risk_pct !== null && (
          <Pill tone="accent" size="md" className="py-1">
            {t.risk(formatPct(totals.risk_pct, 'overview'))}
          </Pill>
        )}
      </SectionHeader>
      {positions.length === 0 ? (
        <p className="rounded-card border border-dashed border-input px-4 py-3 text-sm text-ink-muted">{t.empty}</p>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {positions.map((position) => (
            <PositionCard key={position.trade_id} position={position} now={data.now} />
          ))}
        </div>
      )}
    </section>
  )
}
