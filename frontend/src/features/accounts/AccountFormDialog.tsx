import { useId, useState, type FormEvent, type ReactNode } from 'react'
import { useIsMutating } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/ui/native-select'
import { uk } from '@/i18n/uk'
import { cn } from '@/lib/utils'
import { accountKeys, useCreateAccount, useUpdateAccount } from './api'
import {
  DECIMAL_FIELDS,
  EMPTY_VALUES,
  diffInput,
  normalizeOnInput,
  requiredFields,
  serverFormErrors,
  toInput,
  validate,
  valuesFromAccount,
  type FieldErrors,
  type FormField,
  type FormValues,
} from './form'
import { ACCOUNT_PHASES, ACCOUNT_STATUSES, passwordEnvKey, type Account } from './types'

const t = uk.accounts.form

interface AccountFormDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** null = create a new account. */
  account: Account | null
}

export function AccountFormDialog({ open, onOpenChange, account }: AccountFormDialogProps) {
  const isSaving = useIsMutating({ mutationKey: accountKeys.save }) > 0
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Escape / outside click / close button must not drop a save in flight.
        if (!isSaving) onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{account ? t.editTitle : t.createTitle}</DialogTitle>
          <DialogDescription>
            <span className="text-foreground">{uk.common.requiredMark}</span>{' '}
            {uk.common.requiredLegend} {t.description}
          </DialogDescription>
        </DialogHeader>
        {/* Mounted only while open, so every opening starts from fresh state. */}
        <AccountForm account={account} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}

interface AccountFormProps {
  account: Account | null
  onDone: () => void
}

function AccountForm({ account, onDone }: AccountFormProps) {
  const idPrefix = useId()
  const [values, setValues] = useState<FormValues>(() =>
    account ? valuesFromAccount(account) : EMPTY_VALUES,
  )
  const [touched, setTouched] = useState<ReadonlySet<FormField>>(new Set())
  const [submitted, setSubmitted] = useState(false)
  const [serverErrors, setServerErrors] = useState<FieldErrors>({})
  const [generalError, setGeneralError] = useState(false)

  const createMutation = useCreateAccount()
  const updateMutation = useUpdateAccount()
  const isSaving = createMutation.isPending || updateMutation.isPending

  const isEdit = account !== null
  const required = requiredFields(isEdit)
  const clientErrors = validate(values, isEdit)

  function errorFor(field: FormField): string | undefined {
    if (serverErrors[field]) return serverErrors[field]
    return submitted || touched.has(field) ? clientErrors[field] : undefined
  }

  function setValue(field: FormField, raw: string) {
    setValues((prev) => ({ ...prev, [field]: normalizeOnInput(field, raw) }))
    if (serverErrors[field]) {
      setServerErrors((prev) => ({ ...prev, [field]: undefined }))
    }
  }

  function markTouched(field: FormField) {
    setTouched((prev) => (prev.has(field) ? prev : new Set(prev).add(field)))
  }

  function handleServerError(error: unknown) {
    const mapped = serverFormErrors(error)
    setServerErrors(mapped.fields)
    setGeneralError(mapped.general)
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitted(true)
    setGeneralError(false)
    if (Object.keys(clientErrors).length > 0) {
      const first = Object.keys(clientErrors)[0]
      document.getElementById(`${idPrefix}-${first}`)?.focus()
      return
    }
    const input = toInput(values)

    if (!account) {
      createMutation.mutate(input, {
        onSuccess: () => {
          toast(t.created)
          onDone()
        },
        onError: handleServerError,
      })
      return
    }

    const patch = diffInput(account, input)
    if (Object.keys(patch).length === 0) {
      onDone()
      return
    }
    updateMutation.mutate(
      { id: account.id, patch },
      {
        onSuccess: () => {
          toast(t.updated)
          onDone()
        },
        onError: handleServerError,
      },
    )
  }

  /** Common props for a text input bound to a form field. */
  function inputProps(field: FormField) {
    const error = errorFor(field)
    const isDecimal = DECIMAL_FIELDS.has(field)
    return {
      id: `${idPrefix}-${field}`,
      name: field,
      value: values[field],
      onChange: (e: { target: { value: string } }) => setValue(field, e.target.value),
      onBlur: () => markTouched(field),
      'aria-invalid': error ? true : undefined,
      'aria-required': required.has(field) || undefined,
      'aria-describedby': `${idPrefix}-${field}-msg`,
      disabled: isSaving,
      autoComplete: 'off',
      spellCheck: false,
      ...(isDecimal ? { inputMode: 'decimal' as const, className: 'num text-right' } : {}),
    }
  }

  function field(name: FormField, control: ReactNode, hint?: ReactNode) {
    const error = errorFor(name)
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${idPrefix}-${name}`}>
          {t.fields[name]}
          {required.has(name) && (
            <span className="text-foreground" aria-hidden>
              {uk.common.requiredMark}
            </span>
          )}
        </Label>
        {control}
        <p
          id={`${idPrefix}-${name}-msg`}
          className={cn('min-h-4 text-xs', error ? 'text-destructive' : 'text-muted-foreground')}
        >
          {error ?? hint}
        </p>
      </div>
    )
  }

  const loginDigits = /^\d+$/.test(values.login) ? values.login : null

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      {generalError && (
        <p role="alert" className="rounded-md border border-destructive/50 px-3 py-2 text-xs text-destructive">
          {t.formError}
        </p>
      )}

      <FormSection title={t.sections.main}>
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
          {field('name', <Input {...inputProps('name')} placeholder={t.placeholders.name} />)}
          {field('firm', <Input {...inputProps('firm')} placeholder={t.placeholders.firm} />)}
          {field(
            'program',
            <Input {...inputProps('program')} placeholder={t.placeholders.program} />,
          )}
          <div className="grid grid-cols-2 gap-x-4">
            {field(
              'phase',
              <NativeSelect {...inputProps('phase')}>
                <option value="" disabled>
                  {uk.common.empty}
                </option>
                {ACCOUNT_PHASES.map((phase) => (
                  <option key={phase} value={phase}>
                    {uk.accounts.phase[phase]}
                  </option>
                ))}
              </NativeSelect>,
            )}
            {field(
              'status',
              <NativeSelect {...inputProps('status')}>
                {ACCOUNT_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {uk.accounts.status[status]}
                  </option>
                ))}
              </NativeSelect>,
            )}
          </div>
        </div>
      </FormSection>

      <FormSection title={t.sections.mt5}>
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
          {field(
            'login',
            <Input
              {...inputProps('login')}
              inputMode="numeric"
              className="num"
              placeholder={t.placeholders.login}
            />,
            loginDigits && (
              <>
                {t.hints.passwordKey} <span className="num">{passwordEnvKey(loginDigits)}</span>
              </>
            ),
          )}
          {field('server', <Input {...inputProps('server')} placeholder={t.placeholders.server} />)}
          <div className="sm:col-span-2">
            {field(
              'terminal_path',
              <Input
                {...inputProps('terminal_path')}
                className="num"
                placeholder={t.placeholders.terminal_path}
              />,
              t.hints.terminal_path,
            )}
          </div>
        </div>
      </FormSection>

      <FormSection title={t.sections.balance}>
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-[1fr_6rem_1fr]">
          {field(
            'starting_balance',
            <Input {...inputProps('starting_balance')} placeholder={t.placeholders.money} />,
          )}
          {field(
            'currency',
            <Input
              {...inputProps('currency')}
              className="num uppercase"
              maxLength={3}
              placeholder={t.placeholders.currency}
            />,
          )}
          {field(
            'reference_balance',
            <Input
              {...inputProps('reference_balance')}
              placeholder={isEdit ? t.placeholders.money : values.starting_balance || t.placeholders.money}
            />,
            isEdit ? t.hints.reference_balance : t.hints.reference_balanceCreate,
          )}
        </div>
      </FormSection>

      <FormSection title={t.sections.rules}>
        <div className="grid gap-x-4 gap-y-1 sm:grid-cols-3">
          {field(
            'daily_loss_pct',
            <Input {...inputProps('daily_loss_pct')} placeholder={t.placeholders.pct} />,
            t.hints.pct,
          )}
          {field(
            'max_drawdown_pct',
            <Input {...inputProps('max_drawdown_pct')} placeholder={t.placeholders.pct} />,
            t.hints.pct,
          )}
          {field(
            'profit_target_pct',
            <Input {...inputProps('profit_target_pct')} placeholder={t.placeholders.pct} />,
            t.hints.pct,
          )}
        </div>
      </FormSection>

      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline" disabled={isSaving}>
            {uk.common.cancel}
          </Button>
        </DialogClose>
        <Button type="submit" disabled={isSaving}>
          {isSaving && <Loader2 className="animate-spin" aria-hidden />}
          {isSaving ? t.saving : account ? t.submitEdit : t.submitCreate}
        </Button>
      </DialogFooter>
    </form>
  )
}

function FormSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-2 text-xs font-semibold tracking-wide text-foreground uppercase">
        {title}
      </legend>
      {children}
    </fieldset>
  )
}
