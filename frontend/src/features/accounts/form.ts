/**
 * Account form state and client-side validation mirroring docs/api.md AccountInput
 * and the DB column sizes (text 100, path 500, money NUMERIC(18,2), percent NUMERIC(10,4)).
 * All values stay strings; decimals are never converted to float.
 */
import { isApiError } from '@/api/client'
import { uk } from '@/i18n/uk'
import {
  decimalExceeds,
  isPositiveDecimal,
  normalizeDecimalInput,
  parseDecimalParts,
} from '@/lib/decimal'
import {
  ACCOUNT_PHASES,
  ACCOUNT_STATUSES,
  type Account,
  type AccountInput,
  type AccountPhase,
  type AccountStatus,
} from './types'

export const FORM_FIELDS = [
  'name',
  'firm',
  'program',
  'phase',
  'status',
  'login',
  'server',
  'terminal_path',
  'starting_balance',
  'currency',
  'reference_balance',
  'daily_loss_pct',
  'max_drawdown_pct',
  'profit_target_pct',
] as const satisfies readonly (keyof AccountInput)[]

export type FormField = (typeof FORM_FIELDS)[number]
export type FormValues = Record<FormField, string>
export type FieldErrors = Partial<Record<FormField, string>>

export const REQUIRED_FIELDS: ReadonlySet<FormField> = new Set<FormField>([
  'name',
  'firm',
  'program',
  'phase',
  'login',
  'server',
  'starting_balance',
  'currency',
])

export const DECIMAL_FIELDS: ReadonlySet<FormField> = new Set<FormField>([
  'starting_balance',
  'reference_balance',
  'daily_loss_pct',
  'max_drawdown_pct',
  'profit_target_pct',
])

const TEXT_MAX = 100
const PATH_MAX = 500
const MONEY_INTEGER_DIGITS = 16
const MONEY_FRACTION_DIGITS = 2
const PCT_FRACTION_DIGITS = 4

const v = uk.accounts.validation

export const EMPTY_VALUES: FormValues = {
  name: '',
  firm: '',
  program: '',
  phase: '',
  status: 'active',
  login: '',
  server: '',
  terminal_path: '',
  starting_balance: '',
  currency: 'USD',
  reference_balance: '',
  daily_loss_pct: '',
  max_drawdown_pct: '',
  profit_target_pct: '',
}

export function valuesFromAccount(account: Account): FormValues {
  return {
    name: account.name,
    firm: account.firm,
    program: account.program,
    phase: account.phase,
    status: account.status,
    login: String(account.login),
    server: account.server,
    terminal_path: account.terminal_path ?? '',
    starting_balance: account.starting_balance,
    currency: account.currency,
    reference_balance: account.reference_balance ?? '',
    daily_loss_pct: account.daily_loss_pct ?? '',
    max_drawdown_pct: account.max_drawdown_pct ?? '',
    profit_target_pct: account.profit_target_pct ?? '',
  }
}

/** Applied on every keystroke: comma → dot for decimals, upper-case currency. */
export function normalizeOnInput(field: FormField, raw: string): string {
  if (DECIMAL_FIELDS.has(field)) return normalizeDecimalInput(raw)
  if (field === 'currency') return raw.toUpperCase()
  if (field === 'login') return raw.trim()
  return raw
}

function validateMoney(value: string): string | undefined {
  const parts = parseDecimalParts(value)
  if (!parts) return v.decimal
  if (parts.fraction.length > MONEY_FRACTION_DIGITS) return v.fractionMoney
  if (parts.integer.length > MONEY_INTEGER_DIGITS) return v.tooLarge
  if (!isPositiveDecimal(parts)) return v.positive
  return undefined
}

function validatePct(value: string): string | undefined {
  const parts = parseDecimalParts(value)
  if (!parts) return v.decimal
  if (parts.fraction.length > PCT_FRACTION_DIGITS) return v.fractionPct
  if (decimalExceeds(parts, 100)) return v.pctRange
  return undefined
}

function validateField(field: FormField, raw: string): string | undefined {
  const value = DECIMAL_FIELDS.has(field) ? normalizeDecimalInput(raw) : raw.trim()
  if (value === '') return REQUIRED_FIELDS.has(field) ? v.required : undefined

  switch (field) {
    case 'name':
    case 'firm':
    case 'program':
    case 'server':
      return value.length > TEXT_MAX ? v.tooLong : undefined
    case 'phase':
      return (ACCOUNT_PHASES as readonly string[]).includes(value) ? undefined : v.invalidOption
    case 'status':
      return (ACCOUNT_STATUSES as readonly string[]).includes(value) ? undefined : v.invalidOption
    case 'login':
      return /^\d+$/.test(value) && /[1-9]/.test(value) && Number.isSafeInteger(Number(value))
        ? undefined
        : v.login
    case 'terminal_path':
      if (value.length > PATH_MAX) return v.tooLong
      // Same rule as the backend: the file name after the last \ or / is terminal64.exe.
      return value.split(/[\\/]/).pop()?.toLowerCase() === 'terminal64.exe'
        ? undefined
        : v.terminalPath
    case 'currency':
      return /^[A-Za-z]{3}$/.test(value) ? undefined : v.currency
    case 'starting_balance':
    case 'reference_balance':
      return validateMoney(value)
    case 'daily_loss_pct':
    case 'max_drawdown_pct':
    case 'profit_target_pct':
      return validatePct(value)
  }
}

export function validate(values: FormValues): FieldErrors {
  const errors: FieldErrors = {}
  for (const field of FORM_FIELDS) {
    const error = validateField(field, values[field])
    if (error) errors[field] = error
  }
  return errors
}

function optionalText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function optionalDecimal(value: string): string | null {
  const normalized = normalizeDecimalInput(value)
  return normalized === '' ? null : normalized
}

/** Builds the request body. Call only after `validate` returned no errors. */
export function toInput(values: FormValues): AccountInput {
  return {
    name: values.name.trim(),
    firm: values.firm.trim(),
    program: values.program.trim(),
    phase: values.phase as AccountPhase,
    login: Number(values.login.trim()),
    server: values.server.trim(),
    terminal_path: optionalText(values.terminal_path),
    starting_balance: normalizeDecimalInput(values.starting_balance),
    currency: values.currency.trim().toUpperCase(),
    status: values.status as AccountStatus,
    reference_balance: optionalDecimal(values.reference_balance),
    daily_loss_pct: optionalDecimal(values.daily_loss_pct),
    max_drawdown_pct: optionalDecimal(values.max_drawdown_pct),
    profit_target_pct: optionalDecimal(values.profit_target_pct),
  }
}

/** PATCH body: only fields whose value differs from the stored account. */
export function diffInput(account: Account, input: AccountInput): Partial<AccountInput> {
  const patch: Partial<Record<keyof AccountInput, unknown>> = {}
  for (const field of FORM_FIELDS) {
    if (input[field] !== account[field]) patch[field] = input[field]
  }
  return patch as Partial<AccountInput>
}

function isFormField(key: string): key is FormField {
  return (FORM_FIELDS as readonly string[]).includes(key)
}

export interface ServerFormErrors {
  fields: FieldErrors
  /** The server rejected something that is not a form field (shown above the form). */
  general: boolean
}

/**
 * Maps 422 `details.fields` (field path → English message) and 409 `details.field`
 * to Ukrainian messages next to the fields. The global toast is shown separately.
 */
export function serverFormErrors(error: unknown): ServerFormErrors {
  const result: ServerFormErrors = { fields: {}, general: false }
  if (!isApiError(error)) return result

  if (error.code === 'conflict') {
    const field = error.details?.field
    if (field === 'name') result.fields.name = v.duplicateName
    else if (field === 'login' || field === 'server') result.fields.login = v.duplicateLogin
    else result.general = true
    return result
  }

  if (error.code === 'validation_error') {
    const fields = error.details?.fields
    if (typeof fields !== 'object' || fields === null) {
      result.general = true
      return result
    }
    for (const [path, message] of Object.entries(fields)) {
      // Paths may look like "login" or "body.login"; the English message goes to the console only.
      const field = path.split('.').find(isFormField)
      if (field) result.fields[field] = v.serverRejected
      else result.general = true
      console.warn(`Server rejected ${path}: ${String(message)}`)
    }
  }
  return result
}
