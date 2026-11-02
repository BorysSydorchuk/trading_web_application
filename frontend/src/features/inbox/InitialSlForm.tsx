import { useId, useState, type FormEvent } from 'react'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useSetInitialSl } from '@/features/trades/api'
import { formatPrice } from '@/features/trades/format'
import type { TradeRow } from '@/features/trades/types'
import { uk } from '@/i18n/uk'
import { normalizeDecimalInput } from '@/lib/decimal'
import { cn } from '@/lib/utils'
import { initialSlServerError, validateInitialSl } from './initialSl'

const s = uk.inboxPage.sl

/** Inline "Початковий SL" input for a needs_sl trade. */
export function InitialSlForm({ trade }: { trade: TradeRow }) {
  const id = useId()
  const [value, setValue] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const mutation = useSetInitialSl()

  const clientError = validateInitialSl(value, trade)
  const error = serverError ?? (submitted ? clientError : null)

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitted(true)
    setServerError(null)
    if (clientError) return
    mutation.mutate(
      { id: trade.id, initialSl: normalizeDecimalInput(value) },
      {
        onSuccess: () => toast(s.saved),
        onError: (e) => setServerError(initialSlServerError(e)),
      },
    )
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-2">
        <label htmlFor={`${id}-sl`} className="text-xs whitespace-nowrap text-muted-foreground">
          {s.label}
          <span className="text-foreground" aria-hidden>
            {uk.common.requiredMark}
          </span>
        </label>
        <Input
          id={`${id}-sl`}
          inputMode="decimal"
          autoComplete="off"
          spellCheck={false}
          className="num h-7 w-32 text-right text-xs"
          placeholder={formatPrice(trade.entry_price)}
          value={value}
          onChange={(e) => {
            setValue(normalizeDecimalInput(e.target.value))
            setServerError(null)
          }}
          aria-invalid={error ? true : undefined}
          aria-required
          aria-describedby={`${id}-msg`}
          disabled={mutation.isPending}
        />
        <Button type="submit" size="sm" className="h-7" disabled={mutation.isPending}>
          {mutation.isPending && <Loader2 className="animate-spin" aria-hidden />}
          {mutation.isPending ? s.saving : s.save}
        </Button>
      </div>
      <p id={`${id}-msg`} className={cn('text-xs text-destructive', !error && 'sr-only')} role={error ? 'alert' : undefined}>
        {error}
      </p>
    </form>
  )
}
