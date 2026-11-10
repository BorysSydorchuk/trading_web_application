import { useId } from 'react'
import { NativeSelect } from '@/components/ui/native-select'
import type { Account } from '@/features/accounts/types'
import { uk } from '@/i18n/uk'
import { trimDecimal } from '@/lib/decimal'
import { cn } from '@/lib/utils'
import { DecimalInput, Field } from './Field'
import type { CalculatorFormState, FieldErrors, RiskMode, SlMode } from './formModel'
import { SegmentedToggle } from './SegmentedToggle'
import { symbolLabel } from './symbolLabel'
import type { Direction, SymbolSpec } from './types'

const t = uk.calculator.form

const DIRECTIONS = [
  { value: 'buy', label: uk.trades.direction.buy },
  { value: 'sell', label: uk.trades.direction.sell },
] as const satisfies readonly { value: Direction; label: string }[]
const SL_MODES = [
  { value: 'price', label: t.slModes.price },
  { value: 'points', label: t.slModes.points },
] as const satisfies readonly { value: SlMode; label: string }[]
const RISK_MODES = [
  { value: 'percent', label: t.riskModes.percent },
  { value: 'amount', label: t.riskModes.amount },
] as const satisfies readonly { value: RiskMode; label: string }[]

interface CalculatorFieldsProps {
  form: CalculatorFormState
  errors: FieldErrors
  accounts: readonly Account[]
  account: Account | null
  /** undefined while loading or on error (the symbol select is then disabled). */
  specs: readonly SymbolSpec[] | undefined
  /** Canonical names not found at this broker: shown, never selectable. */
  missing: readonly string[]
  spec: SymbolSpec | null
  onChange: (patch: Partial<CalculatorFormState>) => void
  compact?: boolean
}


export function CalculatorFields({ form, errors, accounts, account, specs, missing, spec, onChange, compact }: CalculatorFieldsProps) {
  const id = useId()
  const sl = form.slMode === 'price'
  const percent = form.riskMode === 'percent'
  const tickHint = spec ? t.tickHint(trimDecimal(spec.tick_size), spec.point === null ? null : trimDecimal(spec.point)) : undefined
  return (
    <div className={cn('grid gap-3', compact ? 'grid-cols-2 lg:grid-cols-3' : 'grid-cols-1 sm:grid-cols-2')}>
      <Field id={`${id}-account`} label={t.account} required error={errors.accountId}>
        <NativeSelect
          id={`${id}-account`}
          value={form.accountId}
          onChange={(e) => onChange({ accountId: e.target.value })}
          aria-invalid={errors.accountId ? true : undefined}
          aria-describedby={`${id}-account-msg`}
        >
          {accounts.map((a) => (
            <option key={a.id} value={String(a.id)}>{t.accountOption(a.name, a.currency)}</option>
          ))}
        </NativeSelect>
      </Field>
      <Field id={`${id}-symbol`} label={t.symbol} required error={errors.symbol}>
        <NativeSelect
          id={`${id}-symbol`}
          value={form.symbol}
          disabled={specs === undefined}
          onChange={(e) => onChange({ symbol: e.target.value })}
          aria-invalid={errors.symbol ? true : undefined}
          aria-describedby={`${id}-symbol-msg`}
        >
          <option value="">{t.symbolPlaceholder}</option>
          {specs?.map((s) => (
            <option key={s.symbol} value={s.symbol}>{symbolLabel(s)}</option>
          ))}
          {specs !== undefined &&
            missing.map((name) => (
                // Distinct value so it never matches a real symbol; the form drops it anyway.
                <option key={`missing-${name}`} value={`missing:${name}`} disabled>{t.symbolMissing(name)}</option>
              ))}
        </NativeSelect>
      </Field>
      <Field id={`${id}-direction`} label={t.direction} required group>
        <SegmentedToggle label={t.direction} value={form.direction} options={DIRECTIONS} onChange={(direction) => onChange({ direction })} />
      </Field>
      <Field id={`${id}-entry`} label={t.entry} required error={errors.entry} hint={tickHint}>
        <DecimalInput id={`${id}-entry`} value={form.entry} invalid={!!errors.entry} onChange={(entry) => onChange({ entry })} />
      </Field>
      <Field
        id={`${id}-sl`}
        label={sl ? t.slPrice : t.slPoints}
        required
        error={errors.sl}
        aside={<SegmentedToggle label={t.slMode} value={form.slMode} options={SL_MODES} onChange={(slMode) => onChange({ slMode })} className="h-6" />}
      >
        <DecimalInput
          id={`${id}-sl`}
          value={sl ? form.slPrice : form.slPoints}
          invalid={!!errors.sl}
          onChange={(value) => onChange(sl ? { slPrice: value } : { slPoints: value })}
        />
      </Field>
      <Field
        id={`${id}-risk`}
        label={percent ? t.riskPercent : t.riskAmount(account?.currency ?? '')}
        required
        error={errors.risk}
        aside={<SegmentedToggle label={t.riskMode} value={form.riskMode} options={RISK_MODES} onChange={(riskMode) => onChange({ riskMode })} className="h-6" />}
      >
        <DecimalInput
          id={`${id}-risk`}
          value={percent ? form.riskPercent : form.riskAmount}
          invalid={!!errors.risk}
          onChange={(value) => onChange(percent ? { riskPercent: value } : { riskAmount: value })}
        />
      </Field>
    </div>
  )
}
