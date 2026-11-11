import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { createQueryClient } from '@/lib/query-client'
import { formatDateTimeBrussels } from '@/lib/time'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { account, marginRequest, result, spec } from './calculator.fixture'
import type { CalculateInput } from './types'
import { f, fillForm, input, r, resultView, rowValue, selectSymbol, serveSetup, submit } from './testUtils'

const e = uk.calculator.errors
const s = uk.calculator.states

function appQueryClient() {
  const client = createQueryClient()
  client.setDefaultOptions({ queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } })
  return client
}

function renderPage() {
  return renderWithProviders(<CalculatorPage />, { path: '/calculator', routes: [{ path: '/settings', element: <p /> }] })
}

/** Calculate answers `body`; the margin request finishes at once (live margin). Returns sent bodies. */
function serveCalculate(answer: () => Response = () => HttpResponse.json(result())) {
  const sent: CalculateInput[] = []
  mockApi(
    http.post('/api/calculator/calculate', async ({ request }) => {
      sent.push((await request.json()) as CalculateInput)
      return answer()
    }),
    http.post('/api/calculator/margin-requests', () =>
      HttpResponse.json(marginRequest({ status: 'done', source: 'mt5', amount: '5300.00', finished_at: '2026-11-10T08:00:02Z' }), { status: 202 }),
    ),
  )
  return sent
}

function errorAnswer(code: string, status: number, details: Record<string, unknown> | null = null) {
  return () => HttpResponse.json({ error: { code, message: 'x', details } }, { status })
}

describe('CalculatorForm accounts and symbols', () => {
  it('offers only active accounts and the exact broker symbols of the selected one', async () => {
    serveSetup({
      accounts: [account({ id: 1, name: 'Активний' }), account({ id: 2, name: 'Пройдений', status: 'passed' }), account({ id: 3, name: 'Злитий', status: 'failed' })],
      specs: [spec({ symbol: 'GER40.cash' }), spec({ symbol: 'XAUUSD', point: null })],
    })
    renderPage()
    const accountSelect = await screen.findByLabelText(f.account, { exact: false })
    expect(within(accountSelect).getAllByRole('option').map((o) => o.textContent)).toEqual([f.accountOption('Активний', 'USD')])
    const symbolSelect = await screen.findByRole('option', { name: 'GER40.cash' })
    expect(symbolSelect).toHaveValue('GER40.cash')
    expect(screen.getByRole('option', { name: f.symbolNeedsSync('XAUUSD') })).toHaveValue('XAUUSD')
  })

  it('shows a hint when there is no active account', async () => {
    serveSetup({ accounts: [account({ status: 'archived' })] })
    renderPage()
    expect(await screen.findByText(s.noAccounts)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: s.toSettings })).toHaveAttribute('href', '/settings')
  })

  it('shows a sync hint and blocks calculate when the account has no specs', async () => {
    serveSetup({ specs: [] })
    renderPage()
    expect(await screen.findByText(s.noSpecs)).toBeInTheDocument()
    expect(screen.getByText(s.noSpecsHint)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: f.submit })).toBeDisabled()
  })

  it('reports a failed accounts load with a retry', async () => {
    mockApi(http.get('/api/accounts', () => HttpResponse.json({ error: { code: 'db_unavailable', message: 'x' } }, { status: 503 })))
    renderPage()
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(s.accountsError)
    expect(alert).toHaveTextContent(uk.errors.db_unavailable)
  })
})

describe('CalculatorForm validation and payload', () => {
  it('marks missing fields and sends nothing', async () => {
    serveSetup()
    const { user } = renderPage()
    await screen.findByRole('option', { name: 'XAUUSD' })
    await user.clear(input(f.riskPercent))
    await submit(user)
    expect(screen.getByText(uk.calculator.validation.symbol)).toBeInTheDocument()
    expect(screen.getAllByText(uk.calculator.validation.required)).toHaveLength(3)
    expect(input(f.entry)).toHaveAttribute('aria-invalid', 'true')
  })

  it('sends decimal strings as typed with a comma turned into a dot and the default 1.0 %', async () => {
    serveSetup()
    const sent = serveCalculate()
    const { user } = renderPage()
    await fillForm(user, { entry: '2650,50', sl: ' 2645,5 ' })
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    expect(sent).toEqual([{ account_id: 1, symbol: 'XAUUSD', direction: 'buy', entry: '2650.50', sl_price: '2645.5', risk_percent: '1.0' }])
  })

  it('sends SL in points and risk as an amount, exactly one field each', async () => {
    serveSetup()
    const sent = serveCalculate(() => HttpResponse.json(result({ risk_percent: null, risk_amount: '250' })))
    const { user } = renderPage()
    await selectSymbol(user)
    await user.click(screen.getByRole('button', { name: uk.trades.direction.sell }))
    await user.type(input(f.entry), '2650.50')
    await user.click(within(screen.getByRole('group', { name: f.slMode })).getByRole('button', { name: f.slModes.points }))
    await user.type(input(f.slPoints), '500')
    await user.click(within(screen.getByRole('group', { name: f.riskMode })).getByRole('button', { name: f.riskModes.amount }))
    await user.type(input(f.riskAmount('USD')), '250,00')
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    expect(sent).toEqual([{ account_id: 1, symbol: 'XAUUSD', direction: 'sell', entry: '2650.50', sl_points: '500', risk_amount: '250.00' }])
    expect(rowValue(r.riskBudget)).toHaveTextContent(r.riskBudgetAmount)
  })
})

describe('CalculatorForm result', () => {
  it('shows lot, real risk, budget, SL, targets, balance source and specs date', async () => {
    serveSetup()
    serveCalculate()
    const { user } = renderPage()
    await fillForm(user)
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    expect(rowValue(r.volume)).toHaveTextContent('2.00')
    expect(rowValue(r.actualRisk)).toHaveTextContent('1 000.00 USD · 1.00%')
    expect(rowValue(r.riskBudget)).toHaveTextContent('1 000.00 USD')
    expect(rowValue(r.riskBudget)).toHaveTextContent(r.riskBudgetPercent('1'))
    expect(rowValue(r.sl)).toHaveTextContent('2645.50')
    expect(rowValue(r.slDistance)).toHaveTextContent(`5.00 · ${r.points('500')}`)
    expect(rowValue(r.target('1.5'))).toHaveTextContent('2658.00')
    expect(rowValue(r.target('2'))).toHaveTextContent('2660.50')
    expect(rowValue(r.target('3'))).toHaveTextContent('2665.50')
    expect(within(resultView()).getByText(r.targets)).toBeInTheDocument()
    expect(rowValue(r.riskBudget)).toHaveTextContent(r.riskBase('100 000.00', 'USD'))
    expect(within(resultView()).queryByText(/Поточний баланс/)).not.toBeInTheDocument()
    expect(within(resultView()).getByText(r.specsAt(formatDateTimeBrussels('2026-11-10T06:00:00Z')), { exact: false })).toBeInTheDocument()
    expect(await within(rowValue(r.margin)).findByText('5 300.00 USD')).toBeInTheDocument()
  })

  it('sizes from the account size and shows the current balance as info in Brussels time', async () => {
    serveSetup()
    serveCalculate(() => HttpResponse.json(result({
      balance: '10000.00', risk_budget: '100.00', current_balance: '10401.70', current_balance_synced_at: '2026-11-10T07:00:00Z',
    })))
    const { user } = renderPage()
    await fillForm(user)
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    expect(rowValue(r.riskBudget)).toHaveTextContent('100.00 USD')
    expect(rowValue(r.riskBudget)).toHaveTextContent(r.riskBase('10 000.00', 'USD'))
    expect(within(resultView()).getByText(r.currentBalance('10 401.70', 'USD', '10.11.2026, 08:00:00'))).toBeInTheDocument()
  })

  it('clears the result when an input changes', async () => {
    serveSetup()
    serveCalculate()
    const { user } = renderPage()
    await fillForm(user)
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    await user.type(input(f.entry), '1')
    expect(screen.queryByRole('region', { name: r.title })).not.toBeInTheDocument()
    expect(screen.getByText(f.changed)).toBeInTheDocument()
  })
})

describe('CalculatorForm superseded state', () => {
  it('drops a calculate answer that arrives after the entry was edited, and posts no margin request', async () => {
    serveSetup()
    let release!: () => void
    const held = new Promise<void>((resolve) => { release = resolve })
    let marginPosts = 0
    let answered = false
    mockApi(
      http.post('/api/calculator/calculate', async () => {
        await held
        answered = true
        return HttpResponse.json(result())
      }),
      http.post('/api/calculator/margin-requests', () => {
        marginPosts += 1
        return HttpResponse.json(marginRequest(), { status: 202 })
      }),
    )
    const { user } = renderPage()
    await fillForm(user)
    await submit(user)
    await user.type(input(f.entry), '5')
    release()
    await waitFor(() => expect(answered).toBe(true))
    await waitFor(() => expect(screen.getByRole('button', { name: f.submit })).toBeEnabled())
    expect(screen.queryByRole('region', { name: r.title })).not.toBeInTheDocument()
    expect(marginPosts).toBe(0)
  })

  it('hides the result when a refetch drops the selected account', async () => {
    serveSetup({ accounts: [account({ id: 1 }), account({ id: 2, name: 'Другий' })] })
    serveCalculate()
    const { user, queryClient } = renderPage()
    await fillForm(user)
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    serveSetup({ accounts: [account({ id: 1, status: 'passed' }), account({ id: 2, name: 'Другий' })] })
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ['accounts'] }) })
    await waitFor(() => expect(screen.queryByRole('region', { name: r.title })).not.toBeInTheDocument())
  })

  it('hides the result when a specs refetch drops the selected symbol', async () => {
    serveSetup({ specs: [spec(), spec({ symbol: 'GER40.cash' })] })
    serveCalculate()
    const { user, queryClient } = renderPage()
    await fillForm(user)
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    serveSetup({ specs: [spec({ symbol: 'GER40.cash' })] })
    await act(async () => { await queryClient.invalidateQueries({ queryKey: ['calculator'] }) })
    await waitFor(() => expect(screen.queryByRole('region', { name: r.title })).not.toBeInTheDocument())
  })

  it('keeps the result when an already selected option is clicked again', async () => {
    serveSetup()
    serveCalculate()
    const { user } = renderPage()
    await fillForm(user)
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    await user.click(screen.getByRole('button', { name: uk.trades.direction.buy }))
    await user.click(within(screen.getByRole('group', { name: f.slMode })).getByRole('button', { name: f.slModes.price }))
    expect(screen.getByRole('region', { name: r.title })).toBeInTheDocument()
  })
})

describe('CalculatorForm server errors', () => {
  /** The app's query client, so its global error toasts are live (as in the browser). */
  async function submitWith(answer: () => Response) {
    serveSetup()
    serveCalculate(answer)
    const { user } = renderWithProviders(<CalculatorPage />, { path: '/calculator', queryClient: appQueryClient() })
    await fillForm(user)
    await submit(user)
    return user
  }

  /** Lets a late toast (if any) render before asserting it is absent. */
  async function settle() {
    await new Promise((resolve) => setTimeout(resolve, 50))
  }

  it.each([
    ['balance_unavailable', 409, null, e.balanceUnavailable],
    ['specs_incomplete', 409, { missing: ['point', 'tick_value_loss'], symbol: 'XAUUSD' }, e.specsIncomplete('point, tick_value_loss')],
    ['specs_invalid', 409, null, e.specsInvalid],
    ['below_min_volume', 422, { volume_min: '0.01', min_volume_risk: '1250.5' }, e.belowMinVolume('0.01', '1 250.50', 'USD')],
    ['invalid_targets', 422, null, e.invalidTargets],
    ['conversion_rate_unavailable', 409, { from_currency: 'EUR', to_currency: 'USD' }, 'Немає курсу EUR→USD, запустіть синхронізацію'],
  ])('shows %s as exactly one readable alert, no toast', async (code, status, details, text) => {
    await submitWith(errorAnswer(code, status, details))
    expect(await screen.findByRole('alert')).toHaveTextContent(text)
    await settle()
    expect(screen.getAllByText(text)).toHaveLength(1)
    expect(screen.queryByText(uk.errors.unknown)).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: r.title })).not.toBeInTheDocument()
  })

  it.each([
    ['validation_error', 422, { fields: { entry: 'bad' } }, f.entry, e.fieldRejected],
    ['off_tick_grid', 422, { fields: ['sl_price'] }, f.slPrice, e.offTickGrid],
    ['invalid_stop', 422, null, f.slPrice, e.invalidStopBuy],
    ['not_found', 404, { symbol: 'XAUUSD' }, f.symbol, e.symbolNotFound('XAUUSD')],
  ])('shows %s once next to the input, no toast', async (code, status, details, label, text) => {
    await submitWith(errorAnswer(code, status, details))
    await waitFor(() => expect(input(label)).toHaveAttribute('aria-invalid', 'true'))
    expect(document.getElementById(`${input(label).id}-msg`)).toHaveTextContent(text)
    await settle()
    expect(screen.getAllByText(text)).toHaveLength(1)
    expect(screen.queryByText(uk.errors.unknown)).not.toBeInTheDocument()
  })

  it.each([
    ['internal_error', () => HttpResponse.json({ error: { code: 'internal_error', message: 'x' } }, { status: 500 }), uk.errors.internal_error],
    ['network failure', () => HttpResponse.error(), uk.errors.network_error],
  ])('shows %s inline and in exactly one toast', async (_name, answer, text) => {
    await submitWith(answer)
    await waitFor(() => expect(screen.getAllByText(text)).toHaveLength(2))
    await settle()
    expect(screen.getAllByText(text)).toHaveLength(2)
    expect(screen.queryByText(uk.errors.unknown)).not.toBeInTheDocument()
  })
})
