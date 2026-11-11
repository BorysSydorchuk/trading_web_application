import type { ReactNode } from 'react'
import { uk } from '@/i18n/uk'
import { trimDecimal } from '@/lib/decimal'
import { formatDateTimeBrussels } from '@/lib/time'
import { cn } from '@/lib/utils'
import { ConversionNote } from './ConversionNote'
import { formatMoney, formatPercent, formatPoints, formatPriceDigits, formatTickValue, formatVolume } from './format'
import { MarginValue } from './MarginValue'
import type { CalculateResult } from './types'
import type { LiveMargin } from './useLiveMargin'

const t = uk.calculator.result

function Row({ label, children, strong }: { label: string; children: ReactNode; strong?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn('num text-right text-sm', strong && 'text-xl font-semibold')}>{children}</dd>
    </div>
  )
}

function currentBalanceNote(result: CalculateResult): string | null {
  if (result.current_balance === null) return null
  const amount = formatMoney(result.current_balance)
  return result.current_balance_synced_at === null
    ? t.currentBalanceNoDate(amount, result.currency)
    : t.currentBalance(amount, result.currency, formatDateTimeBrussels(result.current_balance_synced_at))
}

function budgetNote(result: CalculateResult): string {
  return result.risk_percent === null ? t.riskBudgetAmount : t.riskBudgetPercent(trimDecimal(result.risk_percent))
}

interface CalculatorResultProps {
  result: CalculateResult
  /** Broker name of the symbol; shown in brackets when it differs from the canonical one. */
  brokerSymbol: string | null
  /** Symbol digits for price display; null when the spec is not in the list. */
  digits: number | null
  margin: LiveMargin | null
  compact?: boolean
}

export function CalculatorResult({ result, brokerSymbol, digits, margin, compact }: CalculatorResultProps) {
  const price = (value: string) => formatPriceDigits(value, digits)
  const cur = result.currency
  const currentBalance = compact ? null : currentBalanceNote(result)
  return (
    <section aria-label={t.title} className="flex flex-col gap-2 rounded-lg border p-3">
      <dl className={cn('grid gap-x-6', compact ? 'grid-cols-1 sm:grid-cols-2' : 'grid-cols-1')}>
        <Row label={t.symbol}>
          {result.symbol}
          {brokerSymbol !== null && brokerSymbol !== result.symbol && (
            <span className="ml-1 text-xs text-muted-foreground" title={t.brokerSymbolTitle(brokerSymbol)}>
              {t.brokerSymbol(brokerSymbol)}
            </span>
          )}
        </Row>
        <Row label={t.volume} strong>{formatVolume(result.volume)}</Row>
        <Row label={t.actualRisk}>
          {formatMoney(result.actual_risk)} {cur} · {formatPercent(result.actual_risk_percent)}
        </Row>
        <Row label={t.riskBudget}>
          <span className="flex flex-col items-end">
            <span>
              {formatMoney(result.risk_budget)} {cur}
              <span className="ml-1 text-xs text-muted-foreground">({budgetNote(result)})</span>
            </span>
            <span className="text-xs text-muted-foreground">{t.riskBase(formatMoney(result.balance), cur)}</span>
          </span>
        </Row>
        <Row label={t.sl}>{price(result.sl_price)}</Row>
        <Row label={t.slDistance}>
          {price(result.sl_distance)} · {t.points(formatPoints(result.sl_points))}
        </Row>
        <Row label={t.margin}>
          <MarginValue live={margin} cached={result.margin} digitsPrice={price} />
        </Row>
        {!compact && <Row label={t.lossPerTick}>{t.lossPerTickValue(formatTickValue(result.loss_per_tick), cur)}</Row>}
      </dl>
      {currentBalance !== null && <p className="num text-xs text-muted-foreground">{currentBalance}</p>}
      {result.conversion !== null && <ConversionNote conversion={result.conversion} compact={compact} />}
      <div>
        <h3 className="pt-1 text-xs font-semibold">{t.targets}</h3>
        <dl className={cn('grid gap-x-6', compact ? 'grid-cols-1 sm:grid-cols-3' : 'grid-cols-1')}>
          <Row label={t.target('1.5')}>{price(result.tp_1_5)}</Row>
          <Row label={t.target('2')}>{price(result.tp_2)}</Row>
          <Row label={t.target('3')}>{price(result.tp_3)}</Row>
        </dl>
        <p className="text-xs text-muted-foreground">{t.targetsNote}</p>
      </div>
      <p className="text-xs text-muted-foreground">
        {t.specsAt(formatDateTimeBrussels(result.specs_at))} · {t.feesNote}
      </p>
    </section>
  )
}
