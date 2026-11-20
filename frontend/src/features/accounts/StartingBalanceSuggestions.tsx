import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { formatDecimal } from '@/lib/decimal'
import { errorText } from '@/lib/errors'
import { formatShortDateTimeBrussels } from '@/lib/time'
import { useUpdateAccount } from './api'
import type { Account } from './types'

const t = uk.accounts.startingSuggestion

/**
 * «Початковий баланс» from the MT5 deal history (first deposit), PM 2026-11-20: shown only when it
 * differs from the stored value; the owner confirms with one click (PATCH starting_balance).
 */
export function StartingBalanceSuggestions({ accounts }: { accounts: readonly Account[] }) {
  const pending = accounts.filter((a) => a.starting_balance_suggestion != null)
  if (pending.length === 0) return null
  return (
    <section aria-label={t.title} className="flex flex-col gap-2">
      {pending.map((account) => (
        <SuggestionRow key={account.id} account={account} />
      ))}
    </section>
  )
}

function SuggestionRow({ account }: { account: Account }) {
  const update = useUpdateAccount()
  const suggestion = account.starting_balance_suggestion
  if (suggestion == null) return null
  const amount = `${formatDecimal(suggestion.amount)} ${account.currency}`
  return (
    <div data-testid="starting-balance-suggestion" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-warning-border bg-warning-soft px-4 py-3 text-sm">
      <p className="min-w-0 flex-1">
        <span className="font-medium">{account.name}:</span>{' '}
        {t.text(amount, formatShortDateTimeBrussels(suggestion.time), `${formatDecimal(account.starting_balance)} ${account.currency}`)}
      </p>
      {update.isError && (
        <p role="alert" className="w-full text-xs text-destructive">
          {t.error} {errorText(update.error)}
        </p>
      )}
      <Button
        size="sm"
        disabled={update.isPending}
        onClick={() => update.mutate({ id: account.id, patch: { starting_balance: suggestion.amount } })}
      >
        {update.isPending && <Loader2 className="animate-spin" aria-hidden />}
        {t.apply}
      </Button>
    </div>
  )
}
