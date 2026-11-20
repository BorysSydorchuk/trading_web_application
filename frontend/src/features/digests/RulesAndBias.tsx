import { Card } from '@/components/studio/Card'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { formatPct } from '@/features/dashboard/format'
import { formatR, formatSignedMoney, pnlClass } from '@/features/trades/format'
import { useViolationLabel } from '@/features/trades/violations'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { BLOCK_TITLE, ROW, TABLE_CARD, THEAD } from './tableStyles'
import { BIAS_SCOPES, type BiasScope, type BiasScopeName, type BiasSide, type RulesSection } from './types'

const r = uk.digests.rules
const bi = uk.digests.bias
const EMPTY = uk.common.empty
const TH = 'px-4 py-2 font-medium whitespace-nowrap'
const TD = 'px-4 py-1.5 whitespace-nowrap'
const NUM = `${TD} num text-right`

/** Violations per rule with their signed P&L cost, plus the distinct-trades total line. */
export function RulesTable({ rules, currency }: { rules: RulesSection; currency: string | null }) {
  const ruleLabel = useViolationLabel()
  return (
    <section aria-labelledby="digest-rules" className="flex flex-col gap-3">
      <SectionHeader id="digest-rules" title={r.title} />
      {rules.rules.length === 0 ? (
        <p className="rounded-card border border-dashed border-input bg-surface px-4 py-4 text-sm text-ink-muted">{r.empty}</p>
      ) : (
        <div className={TABLE_CARD}>
          <table aria-label={r.title} className="w-full text-sm">
            <thead className={THEAD}>
              <tr>
                <th scope="col" className={`${TH} text-left`}>{r.rule}</th>
                <th scope="col" className={`${TH} text-right`}>{r.violations}</th>
                <th scope="col" className={`${TH} text-right`}>{r.trades}</th>
                <th scope="col" className={`${TH} text-right`}>{uk.digests.withCurrency(r.pnl, currency)}</th>
              </tr>
            </thead>
            <tbody>
              {rules.rules.map((line) => (
                <tr key={line.rule_key} className={ROW}>
                  <td className={TD}>{ruleLabel(line.rule_key)}</td>
                  <td className={NUM}>{line.violations}</td>
                  <td className={NUM}>{line.trades}</td>
                  <td className={cn(NUM, pnlClass(line.pnl))}>{formatSignedMoney(line.pnl)}</td>
                </tr>
              ))}
              <tr className="border-t border-line bg-track/60 font-medium">
                <th scope="row" className={`${TD} text-left font-medium`}>{r.total}</th>
                <td className={NUM}>{EMPTY}</td>
                <td className={NUM}>{rules.violated_trades}</td>
                <td className={cn(NUM, pnlClass(rules.violated_pnl))}>{formatSignedMoney(rules.violated_pnl)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** Daily / weekly / monthly bias: accuracy of the marked entries and aligned vs counter trades. */
export function BiasSummary({ bias, currency }: { bias: Partial<Record<BiasScopeName, BiasScope>>; currency: string | null }) {
  return (
    <section aria-labelledby="digest-bias" className="flex flex-col gap-3">
      <SectionHeader id="digest-bias" title={bi.title} />
      {/* Cards wrap below ~18rem each instead of squeezing their tables. */}
      <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(100%,18rem),1fr))]">
        {BIAS_SCOPES.map((scope) => {
          const data = bias[scope]
          return data ? <BiasScopeCard key={scope} title={bi.scopes[scope]} scope={data} currency={currency} /> : null
        })}
      </div>
    </section>
  )
}

function BiasScopeCard({ title, scope, currency }: { title: string; scope: BiasScope; currency: string | null }) {
  const { accuracy } = scope
  return (
    <Card as="article" aria-label={title} className="flex min-w-0 flex-col gap-2 px-5 py-4">
      <h3 className={BLOCK_TITLE}>{title}</h3>
      <p className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-ink-muted">{bi.accuracy}</span>
        <span className="num text-base font-semibold">{accuracy.value === null ? EMPTY : formatPct(accuracy.value)}</span>
      </p>
      <p className="num text-right text-xs text-ink-muted">{bi.marked(accuracy.marked, accuracy.total)}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className={THEAD}>
            <tr>
              <th scope="col" className={`${TH} pl-0 text-left`}>{bi.side}</th>
              <th scope="col" className={`${TH} text-right`}>{bi.trades}</th>
              <th scope="col" className={`${TH} text-right`}>{uk.digests.withCurrency(bi.netPnl, currency)}</th>
              <th scope="col" className={`${TH} pr-0 text-right`}>{bi.totalR}</th>
            </tr>
          </thead>
          <tbody>
            <SideRow label={bi.aligned} side={scope.aligned} />
            <SideRow label={bi.counter} side={scope.counter} />
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function SideRow({ label, side }: { label: string; side: BiasSide }) {
  return (
    <tr className={ROW}>
      <th scope="row" className={`${TD} pl-0 text-left font-normal`}>{label}</th>
      <td className={NUM}>{side.trades}</td>
      <td className={cn(NUM, pnlClass(side.net_pnl))}>{formatSignedMoney(side.net_pnl)}</td>
      <td className={`${NUM} pr-0`}>{formatR(side.total_r)}</td>
    </tr>
  )
}
