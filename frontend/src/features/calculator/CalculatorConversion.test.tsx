import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { formatDateTimeBrussels } from '@/lib/time'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { CalculatorPanel } from './CalculatorPanel'
import { conversion, marginRequest, result, spec } from './calculator.fixture'
import { formatRate } from './format'
import type { CalculateResult } from './types'
import { fillForm, r, resultView, rowValue, serveSetup, submit } from './testUtils'

const RATE_AT = '2026-11-10T07:55:00Z'

/** GER40 (GER30 at the broker): EUR profit, USD account, the M5-09 real case. */
const GER_RESULT = result({ loss_per_tick: '0.11091000', conversion: conversion() })

function serveCalculate(body: CalculateResult) {
  mockApi(
    http.post('/api/calculator/calculate', () => HttpResponse.json(body)),
    http.post('/api/calculator/margin-requests', () =>
      HttpResponse.json(marginRequest({ status: 'done', source: 'mt5', amount: '5300.00', finished_at: '2026-11-10T08:00:02Z' }), { status: 202 }),
    ),
  )
}

async function calculate(body: CalculateResult, compact = false) {
  serveSetup({ specs: [spec()] })
  serveCalculate(body)
  const ui = compact ? <CalculatorPanel /> : <CalculatorPage />
  const { user } = renderWithProviders(ui, { path: '/', routes: [{ path: '/calculator', element: <p /> }] })
  await fillForm(user)
  await submit(user)
  return screen.findByRole('region', { name: r.title })
}

describe('Calculator cross-currency conversion (M5-09)', () => {
  it('shows the rate line with the pair, side and Brussels time, and the loss per tick', async () => {
    await calculate(GER_RESULT)
    const line = r.conversionRate('EURUSD', '1.1091', 'ask', formatDateTimeBrussels(RATE_AT))
    expect(within(resultView()).getByText(line)).toBeInTheDocument()
    expect(line).toContain('курс EURUSD 1.1091 (ask) від')
    expect(rowValue(r.lossPerTick)).toHaveTextContent('0.11091 USD за лот')
    expect(screen.queryByText(r.conversionStale)).not.toBeInTheDocument()
    expect(screen.queryByText(/вартість тіку за MT5/)).not.toBeInTheDocument()
  })

  it('warns when the rate is older than 1 h', async () => {
    await calculate(result({ conversion: conversion({ stale: true }) }))
    expect(within(resultView()).getByText(r.conversionStale)).toBeInTheDocument()
    expect(r.conversionStale).toBe('Курс старший за 1 год — результат може бути неточним, запустіть синхронізацію')
  })

  it('shows the MT5 check value next to the rate value when MT5 was used', async () => {
    const check = conversion({ source: 'mt5_check', mt5_loss_per_tick: '0.11200000', mt5_checked_at: RATE_AT })
    await calculate(result({ loss_per_tick: '0.11200000', conversion: check }))
    expect(within(resultView()).getByText('вартість тіку за MT5: 0.112 (курс дає 0.11091)')).toBeInTheDocument()
  })

  it('shows no rate line for a same-currency symbol', async () => {
    await calculate(result())
    expect(screen.queryByText(/^курс /)).not.toBeInTheDocument()
    expect(screen.queryByText(r.conversionStale)).not.toBeInTheDocument()
    expect(rowValue(r.lossPerTick)).toHaveTextContent('1 USD за лот')
  })

  it('keeps the Home panel compact: rate line and stale warning, no MT5 line or loss-per-tick row', async () => {
    const check = conversion({ stale: true, source: 'mt5_check', mt5_loss_per_tick: '0.11200000', mt5_checked_at: RATE_AT })
    await calculate(result({ conversion: check }), true)
    const view = resultView()
    expect(within(view).getByText(r.conversionRate('EURUSD', '1.1091', 'ask', formatDateTimeBrussels(RATE_AT)))).toBeInTheDocument()
    expect(within(view).getByText(r.conversionStale)).toBeInTheDocument()
    expect(within(view).queryByText(/вартість тіку за MT5/)).not.toBeInTheDocument()
    expect(within(view).queryByText(r.lossPerTick)).not.toBeInTheDocument()
  })
})

describe('formatRate', () => {
  it('trims to 4–5 places for rates ≥ 1 and keeps small inverse rates readable', () => {
    expect(formatRate('1.10910000')).toBe('1.1091')
    expect(formatRate('1.10913700')).toBe('1.10914')
    expect(formatRate('157.23000000')).toBe('157.2300')
    expect(formatRate('0.00636000')).toBe('0.00636')
  })
})
