/** Shared helpers for calculator component tests. */
import { screen, within } from '@testing-library/react'
import type { UserEvent } from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import type { Account } from '@/features/accounts/types'
import { uk } from '@/i18n/uk'
import { mockApi } from '@/test/server'
import { account, spec } from './calculator.fixture'
import type { SymbolSpec } from './types'

export const f = uk.calculator.form
export const r = uk.calculator.result

interface SetupOptions {
  accounts?: Account[]
  specs?: SymbolSpec[]
  /** Canonical names not found at the broker. */
  missing?: string[]
}

export function serveSetup({ accounts = [account()], specs = [spec()], missing = [] }: SetupOptions = {}) {
  mockApi(
    http.get('/api/accounts', () => HttpResponse.json({ items: accounts })),
    http.get('/api/accounts/:id/symbol-specs', () => HttpResponse.json({ items: specs, missing })),
  )
}

/** Input by its visible label (the label also holds the required "*"). */
export function input(label: string): HTMLElement {
  return screen.getByLabelText(label, { exact: false })
}

export async function selectSymbol(user: UserEvent, symbol = 'XAUUSD') {
  await screen.findByRole('option', { name: symbol })
  await user.selectOptions(input(f.symbol), symbol)
}

export async function fillForm(user: UserEvent, values: { entry?: string; sl?: string } = {}) {
  await selectSymbol(user)
  await user.type(input(f.entry), values.entry ?? '2650.50')
  await user.type(input(f.slPrice), values.sl ?? '2645.50')
}

export async function submit(user: UserEvent) {
  await user.click(screen.getByRole('button', { name: f.submit }))
}

export function resultView(): HTMLElement {
  return screen.getByRole('region', { name: r.title })
}

/** The value cell (<dd>) of a result row. */
export function rowValue(label: string): HTMLElement {
  const dt = within(resultView()).getByText(label)
  const dd = dt.nextElementSibling
  if (!(dd instanceof HTMLElement)) throw new Error(`No value for ${label}`)
  return dd
}
