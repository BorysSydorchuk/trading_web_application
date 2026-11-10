import type { FormEvent, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { useAccounts } from '@/features/accounts/api'
import type { Account } from '@/features/accounts/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { CalculatorFields } from './CalculatorFields'
import { CalculatorResult } from './CalculatorResult'
import { useCalculatorForm } from './useCalculatorForm'

const t = uk.calculator
const s = t.states

interface CalculatorFormProps {
  /** Home panel layout: denser field grid, result below the form. */
  compact?: boolean
}

function Notice({ title, hint, children }: { title: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border p-4">
      <p className="text-sm">{title}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
      {children}
    </div>
  )
}

function LoadError({ title, error, onRetry, busy }: { title: string; error: unknown; onRetry: () => void; busy: boolean }) {
  return (
    <div role="alert">
      <Notice title={title} hint={errorText(error)}>
        <Button variant="outline" size="sm" disabled={busy} onClick={onRetry}>{uk.common.retry}</Button>
      </Notice>
    </div>
  )
}

/** Position-size calculator (PRD 6.8): only active accounts; symbols from that account's synced specs. */
export function CalculatorForm({ compact }: CalculatorFormProps) {
  const accounts = useAccounts(false)
  if (accounts.isPending) return <p role="status" className="text-sm text-muted-foreground">{s.loadingAccounts}</p>
  if (accounts.isError) {
    return <LoadError title={s.accountsError} error={accounts.error} busy={accounts.isFetching} onRetry={() => void accounts.refetch()} />
  }
  const active = accounts.data.items.filter((a) => a.status === 'active')
  if (active.length === 0) {
    return (
      <Notice title={s.noAccounts} hint={s.noAccountsHint}>
        <Button asChild variant="outline" size="sm"><Link to="/settings">{s.toSettings}</Link></Button>
      </Notice>
    )
  }
  return <Calculator accounts={active} compact={compact} />
}

function Calculator({ accounts, compact }: { accounts: readonly Account[]; compact?: boolean }) {
  const calc = useCalculatorForm(accounts)
  const { specsQuery, specs } = calc

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    calc.submit()
  }

  const specsState = (() => {
    if (specsQuery.isPending) return <p role="status" className="text-xs text-muted-foreground">{s.loadingSpecs}</p>
    if (specsQuery.isError) {
      return <LoadError title={s.specsError} error={specsQuery.error} busy={specsQuery.isFetching} onRetry={() => void specsQuery.refetch()} />
    }
    if (specs?.length === 0) return <Notice title={s.noSpecs} hint={s.noSpecsHint} />
    return null
  })()

  return (
    <div className={cn('grid gap-4', !compact && 'lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]')}>
      <form aria-label={t.form.label} onSubmit={handleSubmit} noValidate className="flex flex-col gap-3">
        <CalculatorFields
          form={calc.form}
          errors={calc.errors}
          accounts={accounts}
          account={calc.account}
          specs={specs}
          spec={calc.spec}
          onChange={calc.update}
          compact={compact}
        />
        {specsState}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" size="sm" disabled={calc.pending || !specs?.length}>
            {calc.pending && <Loader2 className="animate-spin" aria-hidden />}
            {calc.pending ? t.form.calculating : t.form.submit}
          </Button>
          <span className="text-xs text-muted-foreground">
            {uk.common.requiredMark} {uk.common.requiredLegend}
          </span>
        </div>
      </form>
      <div className="flex flex-col gap-2">
        {calc.generalError && (
          <p role="alert" className="rounded-lg border border-destructive/50 p-3 text-sm text-destructive">{calc.generalError}</p>
        )}
        {calc.result ? (
          <CalculatorResult result={calc.result} digits={calc.spec?.digits ?? null} margin={calc.margin} compact={compact} />
        ) : (
          !calc.generalError && (
            <p className="text-xs text-muted-foreground">{calc.changed ? t.form.changed : s.empty}</p>
          )
        )}
      </div>
    </div>
  )
}
