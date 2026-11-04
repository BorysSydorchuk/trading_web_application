/** Label/value rows shared by the trade detail dialog and the Describe screen. */
import type { ReactNode } from 'react'
import { uk } from '@/i18n/uk'
import { violationSourceLabel } from './format'
import type { TradeDetail } from './types'
import { useViolationLabel } from './violations'

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1.5">
      <h3 className="text-xs font-semibold tracking-wide uppercase">{title}</h3>
      <dl className="flex flex-col">{children}</dl>
    </section>
  )
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/50 py-1 text-sm last:border-b-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  )
}

export function ViolationList({ trade }: { trade: TradeDetail }) {
  const label = useViolationLabel()
  if (trade.rule_violations.length === 0) {
    return <p className="text-xs text-muted-foreground">{uk.tradeDetail.noViolations}</p>
  }
  return (
    <ul className="flex flex-col gap-1.5">
      {trade.rule_violations.map((v) => (
        <li key={`${v.rule_key}-${v.source}`} className="flex flex-wrap items-baseline gap-2 text-sm">
          <span className="rounded border border-loss/30 bg-loss/10 px-1.5 py-px text-xs text-loss">
            {label(v.rule_key)}
          </span>
          <span className="text-xs text-muted-foreground">{violationSourceLabel(v.source)}</span>
          {v.details && <span className="text-xs text-muted-foreground">{v.details}</span>}
        </li>
      ))}
    </ul>
  )
}
