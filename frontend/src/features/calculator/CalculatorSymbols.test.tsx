/** M5-08 canonical symbols: canonical value, broker name in labels, missing symbols (docs/api.md). */
import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { marginRequest, result, spec } from './calculator.fixture'
import type { CalculateInput } from './types'
import { f, input, r, rowValue, serveSetup, submit } from './testUtils'

const s = uk.calculator.states
const GER = spec({ symbol: 'GER40', broker_symbol: 'GER30', point: '0.1', tick_size: '0.1', digits: 1 })

function renderPage() {
  return renderWithProviders(<CalculatorPage />, { path: '/calculator' })
}

function serveCalculate() {
  const sent: { calculate: CalculateInput[]; margin: CalculateInput[] } = { calculate: [], margin: [] }
  mockApi(
    http.post('/api/calculator/calculate', async ({ request }) => {
      sent.calculate.push((await request.json()) as CalculateInput)
      return HttpResponse.json(result({ symbol: 'GER40', entry: '22000.0', sl_price: '21950.0' }))
    }),
    http.post('/api/calculator/margin-requests', async ({ request }) => {
      sent.margin.push((await request.json()) as CalculateInput)
      return HttpResponse.json(marginRequest({ symbol: 'GER40', status: 'done', source: 'mt5', amount: '1100.00' }), { status: 202 })
    }),
  )
  return sent
}

function symbolSelect(): HTMLSelectElement {
  return input(f.symbol) as HTMLSelectElement
}

describe('CalculatorForm canonical symbols', () => {
  it('labels a symbol with its broker name when it differs, plain when the same', async () => {
    serveSetup({ specs: [spec({ symbol: 'EURUSD' }), GER], missing: [] })
    renderPage()
    expect(await screen.findByRole('option', { name: 'EURUSD' })).toHaveValue('EURUSD')
    expect(screen.getByRole('option', { name: f.symbolWithBroker('GER40', 'GER30') })).toHaveValue('GER40')
    expect(f.symbolWithBroker('GER40', 'GER30')).toBe('GER40 (GER30)')
  })

  it('adds the needs-sync note only to an incomplete spec, after the broker name', async () => {
    serveSetup({ specs: [spec({ ...GER, tick_value_loss: null }), spec({ symbol: 'EURUSD' })], missing: [] })
    renderPage()
    const option = await screen.findByRole('option', { name: f.symbolNeedsSync(f.symbolWithBroker('GER40', 'GER30')) })
    expect(option).toHaveTextContent('GER40 (GER30) (потрібна синхронізація)')
    expect(option).toHaveValue('GER40')
    expect(screen.getByRole('option', { name: 'EURUSD' })).toBeInTheDocument()
  })

  it('shows missing symbols as disabled options that cannot be selected', async () => {
    serveSetup({ specs: [spec({ symbol: 'EURUSD' })], missing: ['GER40'] })
    const { user } = renderPage()
    const option = await screen.findByRole('option', { name: f.symbolMissing('GER40') })
    expect(option).toHaveTextContent('символ не знайдено у брокера: GER40')
    expect(option).toBeDisabled()
    await user.selectOptions(symbolSelect(), option).catch(() => undefined)
    expect(symbolSelect()).toHaveValue('')
    expect(within(symbolSelect()).getAllByRole('option').map((o) => o.textContent)).toEqual([
      f.symbolPlaceholder, 'EURUSD', f.symbolMissing('GER40'),
    ])
  })

  it('keeps the no-specs hint when every configured symbol is missing', async () => {
    serveSetup({ specs: [], missing: ['GER40'] })
    renderPage()
    expect(await screen.findByText(s.noSpecs)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: f.symbolMissing('GER40') })).toBeDisabled()
    expect(screen.getByRole('button', { name: f.submit })).toBeDisabled()
  })

  it('sends the canonical name and shows the broker name beside it in the result', async () => {
    serveSetup({ specs: [GER], missing: [] })
    const sent = serveCalculate()
    const { user } = renderPage()
    await screen.findByRole('option', { name: f.symbolWithBroker('GER40', 'GER30') })
    await user.selectOptions(symbolSelect(), 'GER40')
    await user.type(input(f.entry), '22000.0')
    await user.type(input(f.slPrice), '21950.0')
    await submit(user)
    await screen.findByRole('region', { name: r.title })
    expect(sent.calculate.map((b) => b.symbol)).toEqual(['GER40'])
    await waitFor(() => expect(sent.margin.map((b) => b.symbol)).toEqual(['GER40']))
    expect(rowValue(r.symbol)).toHaveTextContent(/^GER40\s*\(GER30\)$/)
    expect(within(rowValue(r.symbol)).getByText(r.brokerSymbol('GER30'))).toHaveAttribute('title', r.brokerSymbolTitle('GER30'))
  })

  it('keeps the no-specs hint when the account has no spec rows and nothing is missing', async () => {
    serveSetup({ specs: [], missing: [] })
    renderPage()
    expect(await screen.findByText(s.noSpecs)).toBeInTheDocument()
    expect(screen.getByText(s.noSpecsHint)).toBeInTheDocument()
    expect(within(symbolSelect()).getAllByRole('option').map((o) => o.textContent)).toEqual([f.symbolPlaceholder])
    expect(screen.getByRole('button', { name: f.submit })).toBeDisabled()
  })
})
