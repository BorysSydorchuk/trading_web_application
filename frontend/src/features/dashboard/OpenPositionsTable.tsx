import { directionLabel, formatPrice, formatVolume } from '@/features/trades/format'
import { uk } from '@/i18n/uk'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { formatPct } from './format'
import type { OpenPosition } from './types'

const p = uk.dashboard.positions
const c = p.columns
const EMPTY = uk.common.empty

const TH = 'px-3 py-2 font-medium whitespace-nowrap'
const TD = 'px-3 py-1.5 whitespace-nowrap'
const NUM = `${TD} num text-right`

/** Open positions in the API order (open time ascending); times in Europe/Brussels. */
export function OpenPositionsTable({ positions }: { positions: readonly OpenPosition[] }) {
  return (
    <section aria-labelledby="dashboard-positions" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="dashboard-positions" className="text-sm font-semibold">{p.title}</h2>
        <span className="text-xs text-muted-foreground">{p.timeZoneNote}</span>
      </div>
      {positions.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-3 text-sm text-muted-foreground">{p.empty}</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border">
          <table aria-label={p.title} className="w-full text-sm">
            <thead className="bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th scope="col" className={`${TH} text-left`}>{c.account}</th>
                <th scope="col" className={`${TH} text-left`}>{c.symbol}</th>
                <th scope="col" className={`${TH} text-left`}>{c.direction}</th>
                <th scope="col" className={`${TH} text-right`}>{c.volume}</th>
                <th scope="col" className={`${TH} text-right`}>{c.entry}</th>
                <th scope="col" className={`${TH} text-right`}>{c.sl}</th>
                <th scope="col" className={`${TH} text-right`}>{c.risk}</th>
                <th scope="col" className={`${TH} text-right`}>{c.openTime}</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((row) => (
                <tr key={row.trade_id} className="border-t">
                  <td className={TD}>{row.account_name}</td>
                  <td className={`${TD} font-medium`}>{row.symbol}</td>
                  <td className={TD}>{directionLabel(row.direction)}</td>
                  <td className={NUM}>{formatVolume(row.volume)}</td>
                  <td className={NUM}>{formatPrice(row.entry_price)}</td>
                  <td className={NUM}>{formatPrice(row.initial_sl)}</td>
                  <td className={NUM}>{row.risk_pct === null ? EMPTY : formatPct(row.risk_pct)}</td>
                  <td className={NUM}>{formatShortDateTimeBrussels(row.open_time)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
