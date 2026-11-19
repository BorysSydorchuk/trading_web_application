/** Label/value rows shared by the trade detail dialog and the Describe screen. */
import type { ReactNode } from 'react'
import { uk } from '@/i18n/uk'
import { useJournalFields } from './api'
import { violationSourceLabel } from './format'
import type { JournalValue, TradeDetail } from './types'
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
        <li key={`${v.rule_key}-${v.source}`} className="flex flex-col gap-0.5 text-sm">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="rounded border border-loss/30 bg-loss/10 px-1.5 py-px text-xs text-loss">
              {label(v.rule_key)}
            </span>
            <span className="text-xs text-muted-foreground">{violationSourceLabel(v.source)}</span>
          </div>
          {/* What the rules engine saw (e.g. which daily limit was hit); migrated rows start with the old key. */}
          {v.details && <p className="num text-xs break-words text-muted-foreground">{v.details}</p>}
        </li>
      ))}
    </ul>
  )
}

function isFilled(value: JournalValue | undefined): boolean {
  if (value === undefined || value === null) return false
  if (Array.isArray(value)) return value.length > 0
  return typeof value !== 'string' || value.trim() !== ''
}

/**
 * M8-04..08: old read-only journal fields (`legacy: true`) the trade still has a value for,
 * as «Старе значення: …». Nothing when there are none (or the field list is unavailable).
 */
export function LegacyValues({ trade }: { trade: TradeDetail }) {
  const { data } = useJournalFields()
  const rows = (data?.fields ?? [])
    .filter((field) => field.legacy === true && isFilled(trade.journal[field.key]))
    .map((field) => {
      const value = trade.journal[field.key]
      const values = Array.isArray(value) ? value : [String(value)]
      const labels = values.map((v) => field.options?.find((o) => o.value === v)?.label ?? v)
      return { key: field.key, label: field.label, value: uk.describe.form.legacyValue(labels.join(', ')) }
    })
  if (rows.length === 0) return null
  return (
    <Section title={uk.tradeDetail.legacyTitle}>
      {rows.map((row) => (
        <Row key={row.key} label={row.label}>
          <span className="text-muted-foreground">{row.value}</span>
        </Row>
      ))}
    </Section>
  )
}
