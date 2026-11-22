import { useMemo } from 'react'
import { SectionHeader } from '@/components/studio/SectionHeader'
import { formatPct } from '@/features/dashboard/format'
import { useJournalFields } from '@/features/trades/api'
import { formatR, formatSignedMoney, pnlClass, sessionLabel, weekdayLabel } from '@/features/trades/format'
import type { JournalField } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { BreakdownMatrix } from './BreakdownMatrix'
import { inOptionOrder, optionLabel, type FieldMap } from './breakdownLabels'
import { BLOCK_TITLE, ROW, THEAD, TITLED_TABLE_CARD } from './tableStyles'
import { TimeBreakdownCard } from './TimeBreakdownCard'
import type { Breakdown, GroupKey } from './types'

const t = uk.digests.breakdowns
const EMPTY = uk.common.empty
const TH = 'px-4 py-1.5 font-medium whitespace-nowrap'
const TD = 'px-4 py-1.5 whitespace-nowrap'
const NUM = `${TD} num text-right`
/** `poi_types__combo`: one group per distinct selection, values joined « + » (docs/api.md M8-04..08). */
const COMBO_SUFFIX = '__combo'
const COMBO_JOIN = ' + '
/** Snapshots from before M8-04..08 have a single-choice `poi_type` breakdown: same options as `poi_types`. */
const RENAMED_FIELDS: Readonly<Record<string, string>> = { poi_type: 'poi_types' }

/** Trade fields of the snapshot; every other breakdown is a journal field with «заповнено N/M». */
const TRADE_FIELD_LABELS: Readonly<Record<string, string>> = {
  symbol: uk.trades.columns.symbol,
  session: uk.trades.columns.session,
  hour: uk.trades.columns.hour,
  weekday: uk.trades.columns.weekday,
  bias_alignment: uk.trades.columns.bias_alignment,
}

/** Shown as pastel cells instead of a table. */
const TIME_FIELDS: ReadonlySet<string> = new Set(['weekday', 'hour'])

type ScalarKey = Exclude<GroupKey, null | readonly (string | null)[]>

function tradeKeyLabel(field: string, key: ScalarKey): string {
  if (field === 'session') return sessionLabel(String(key))
  if (field === 'weekday' && typeof key === 'number') return weekdayLabel(key)
  if (field === 'hour') return t.hour(String(key).padStart(2, '0'))
  if (field === 'bias_alignment') {
    const labels: Readonly<Record<string, string>> = uk.bias.alignment
    return Object.hasOwn(labels, String(key)) ? (labels[String(key)] ?? String(key)) : String(key)
  }
  return String(key)
}

function journalKeyLabel(field: JournalField | undefined, key: ScalarKey): string {
  if (typeof key === 'boolean') return key ? uk.trades.yes : uk.trades.no
  return optionLabel(field, String(key))
}

/** Breakdown tables in the snapshot order (trade fields, analytics journal fields, combinations, matrix). */
export function BreakdownTables({ breakdowns, currency }: { breakdowns: Record<string, Breakdown>; currency: string | null }) {
  const { data } = useJournalFields()
  const fields: FieldMap = useMemo(() => new Map((data?.fields ?? []).map((f) => [f.key, f])), [data])
  const entries = Object.entries(breakdowns)
  return (
    <section aria-labelledby="digest-breakdowns" className="flex flex-col gap-3">
      <SectionHeader id="digest-breakdowns" title={t.title} />
      <div className="grid gap-4 lg:grid-cols-2">
        {entries.map(([name, breakdown]) =>
          breakdown.kind === 'matrix' ? (
            <BreakdownMatrix key={name} name={name} breakdown={breakdown} fields={fields} currency={currency} />
          ) : (
            <BreakdownTable key={name} name={name} breakdown={breakdown} fields={fields} currency={currency} />
          ),
        )}
      </div>
    </section>
  )
}

interface BreakdownTableProps {
  name: string
  breakdown: Breakdown
  fields: FieldMap
  currency: string | null
}

interface TableView {
  title: string
  label: (key: ScalarKey) => string
  showCoverage: boolean
  note: string | null
  /** The journal field whose current option order sorts the rows. */
  orderField?: JournalField
}

/** Title, key labels and note of a `field` or `combination` breakdown (no `kind` = field). */
function tableView(name: string, breakdown: Breakdown, fields: FieldMap): TableView {
  if (breakdown.kind === 'combination') {
    const base = name.endsWith(COMBO_SUFFIX) ? name.slice(0, -COMBO_SUFFIX.length) : name
    const field = fields.get(base)
    return {
      title: t.combinationTitle(field?.label ?? base),
      label: (key) => String(key).split(COMBO_JOIN).map((value) => optionLabel(field, value)).join(COMBO_JOIN),
      showCoverage: true,
      note: null,
    }
  }
  if (Object.hasOwn(TRADE_FIELD_LABELS, name)) {
    return { title: TRADE_FIELD_LABELS[name] ?? name, label: (key) => tradeKeyLabel(name, key), showCoverage: false, note: null }
  }
  const renamed = Object.hasOwn(RENAMED_FIELDS, name) && !fields.has(name)
  const field = fields.get(renamed ? (RENAMED_FIELDS[name] ?? name) : name)
  return {
    title: field?.label ?? name,
    orderField: field,
    label: (key) => journalKeyLabel(field, key),
    showCoverage: true,
    // A multi field counts a trade once in each of its values, so the rows add up to more trades.
    // An old single-choice breakdown shown with the new field's labels does not.
    note: field?.type === 'multi_enum' && !renamed ? t.multiNote : null,
  }
}

function BreakdownTable({ name, breakdown, fields, currency }: BreakdownTableProps) {
  const view = tableView(name, breakdown, fields)
  const label = (key: GroupKey) => {
    if (key === null) return t.notFilled
    return Array.isArray(key) ? key.map((part) => part ?? t.notFilled).join(COMBO_JOIN) : view.label(key as ScalarKey)
  }
  if (TIME_FIELDS.has(name)) {
    return <TimeBreakdownCard title={view.title} breakdown={breakdown} label={label} currency={currency} />
  }
  return (
    <article aria-label={view.title} className={TITLED_TABLE_CARD}>
      <div className="flex items-baseline justify-between gap-2 px-4 pt-1">
        <h3 className={BLOCK_TITLE}>{view.title}</h3>
        {view.showCoverage && (
          <span className="num text-xs text-ink-muted">
            {t.coverage(breakdown.coverage.filled, breakdown.coverage.total)}
          </span>
        )}
      </div>
      {view.note && <p className="px-4 text-[11px] text-ink-muted">{view.note}</p>}
      <table className="w-full text-sm">
        <thead className={THEAD}>
          <tr>
            <th scope="col" className={`${TH} text-left`}>{t.key}</th>
            <th scope="col" className={`${TH} text-right`}>{t.trades}</th>
            <th scope="col" className={`${TH} text-right`}>{uk.digests.withCurrency(t.netPnl, currency)}</th>
            <th scope="col" className={`${TH} text-right`}>{t.totalR}</th>
            <th scope="col" className={`${TH} text-right`}>{t.winRate}</th>
          </tr>
        </thead>
        <tbody>
          {inOptionOrder(view.orderField, breakdown.groups).map((group) => (
            <tr key={String(group.key)} className={ROW}>
              <td className={cn(TD, group.key === null && 'text-ink-muted')}>{label(group.key)}</td>
              <td className={NUM}>{group.trades}</td>
              <td className={cn(NUM, pnlClass(group.net_pnl))}>{formatSignedMoney(group.net_pnl)}</td>
              <td className={NUM}>{formatR(group.total_r)}</td>
              <td className={NUM}>{group.win_rate === null ? EMPTY : formatPct(group.win_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  )
}
