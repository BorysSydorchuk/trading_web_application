/**
 * Calculator form state, submit and result. Every input change or new submit bumps a version;
 * answers (calculate, live margin) for an older version are discarded, so a stale lot size or
 * margin is never shown for changed inputs.
 */
import { useRef, useState } from 'react'
import type { Account } from '@/features/accounts/types'
import { showErrorToast } from '@/lib/errors'
import { useCalculate, useSymbolSpecs } from './api'
import { buildPayload, INITIAL_FORM, validateForm, type CalculatorFormState, type FieldErrors } from './formModel'
import { mapCalculatorError, type CalculatorErrors } from './serverErrors'
import type { CalculateResult } from './types'
import { useLiveMargin, type MarginJob } from './useLiveMargin'

function pickAccountId(form: CalculatorFormState, accounts: readonly Account[]): string {
  if (accounts.some((a) => String(a.id) === form.accountId)) return form.accountId
  return accounts[0] ? String(accounts[0].id) : ''
}

export function useCalculatorForm(accounts: readonly Account[]) {
  const [rawForm, setForm] = useState<CalculatorFormState>(INITIAL_FORM)
  const [submitted, setSubmitted] = useState(false)
  const [serverErrors, setServerErrors] = useState<CalculatorErrors | null>(null)
  const [result, setResult] = useState<CalculateResult | null>(null)
  const [job, setJob] = useState<MarginJob | null>(null)
  const [changed, setChanged] = useState(false)
  const version = useRef(0)
  const mutation = useCalculate()

  // The first active account is preselected; a symbol that left the list is dropped.
  const accountId = pickAccountId(rawForm, accounts)
  const specsQuery = useSymbolSpecs(accountId === '' ? null : Number(accountId))
  const specs = specsQuery.data?.items
  const symbol = specs?.some((s) => s.symbol === rawForm.symbol) ? rawForm.symbol : ''
  const form: CalculatorFormState = { ...rawForm, accountId, symbol }
  const account = accounts.find((a) => String(a.id) === accountId) ?? null
  const spec = specs?.find((s) => s.symbol === symbol) ?? null
  // A refetch can drop the selected account or symbol: never show (or keep polling for) a result
  // that no longer matches the form.
  const current = result !== null && String(result.account_id) === accountId && result.symbol === symbol
  const margin = useLiveMargin(current ? job : null)

  function supersede() {
    version.current += 1
    setResult(null)
    setJob(null)
    setServerErrors(null)
  }

  function update(patch: Partial<CalculatorFormState>) {
    // Re-selecting the current value (e.g. the pressed toggle) changes nothing.
    const keys = Object.keys(patch) as (keyof CalculatorFormState)[]
    if (keys.every((key) => patch[key] === form[key])) return
    const nextAccount = patch.accountId !== undefined && patch.accountId !== accountId
    setForm((prev) => ({ ...prev, accountId, symbol, ...(nextAccount ? { symbol: '' } : {}), ...patch }))
    if (result || mutation.isPending) setChanged(true)
    supersede()
  }

  function submit() {
    setSubmitted(true)
    if (Object.keys(validateForm(form)).length > 0) return
    const payload = buildPayload(form)
    supersede()
    setChanged(false)
    const current = version.current
    const currency = account?.currency ?? ''
    mutation.mutate(payload, {
      onSuccess: (data) => {
        if (current !== version.current) return
        setResult(data)
        setJob({ version: current, input: payload })
      },
      onError: (error) => {
        if (current !== version.current) return
        const mapped = mapCalculatorError(error, form, currency)
        setServerErrors(mapped)
        if (mapped.unexpected) showErrorToast(error)
      },
    })
  }

  const clientErrors: FieldErrors = submitted ? validateForm(form) : {}
  const errors: FieldErrors = { ...clientErrors, ...serverErrors?.fields }
  return {
    form,
    account,
    specsQuery,
    specs,
    spec,
    update,
    submit,
    errors,
    generalError: serverErrors?.general ?? null,
    result: current ? result : null,
    margin,
    changed: changed && result === null && !mutation.isPending,
    pending: mutation.isPending,
  }
}
