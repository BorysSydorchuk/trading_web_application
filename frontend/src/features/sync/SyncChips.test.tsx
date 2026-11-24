import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { AccountPlatform } from '@/features/accounts/types'
import { account } from '@/features/calculator/calculator.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import type { SyncStatusRow } from './api'
import { syncErrorText } from './errors'
import { SyncChips } from './SyncChips'

function row(overrides: Partial<SyncStatusRow> = {}): SyncStatusRow {
  return {
    account_id: 2, account_name: 'CT Demo', state: 'error', last_attempt_utc: '2026-11-23T10:00:00Z',
    last_success_utc: null, error_code: 'token_expired', error_message: 'raw english', server_offset_hours: null,
    open_positions: 0, ...overrides,
  }
}

function serve(items: SyncStatusRow[], platform: AccountPlatform = 'ctrader') {
  mockApi(
    http.get('/api/sync/status', () => HttpResponse.json({ items })),
    http.get('/api/accounts', () => HttpResponse.json({ items: [account({ id: 2, platform })] })),
  )
}

describe('SyncChips: cTrader', () => {
  it.each(['token_expired', 'token_invalid'])('%s says to connect cTrader again', async (code) => {
    serve([row({ error_code: code })])
    renderWithProviders(<SyncChips />)
    expect(await screen.findByRole('button', { name: /CT Demo \(cTrader\).*Підключіть cTrader знову/ })).toBeInTheDocument()
    expect(screen.queryByText(/raw english/)).not.toBeInTheDocument()
  })

  it('details show the platform and hide the MT5 server time and open positions', async () => {
    serve([row()])
    const { user } = renderWithProviders(<SyncChips />)
    await user.click(await screen.findByRole('button', { name: /CT Demo \(cTrader\)/ }))
    const details = await screen.findByRole('dialog')
    expect(within(details).getByText(uk.sync.details.platform)).toBeInTheDocument()
    expect(within(details).queryByText(uk.sync.details.serverOffset)).not.toBeInTheDocument()
    expect(within(details).queryByText(uk.sync.details.openPositions)).not.toBeInTheDocument()
  })

  it('an MT5 account keeps its details and its timeout text', async () => {
    serve([row({ account_name: 'MT Acc', error_code: 'timeout', server_offset_hours: 2 })], 'mt5')
    const { user } = renderWithProviders(<SyncChips />)
    await user.click(await screen.findByRole('button', { name: `MT Acc (MT5): ${uk.sync.errors.timeout}` }))
    const details = await screen.findByRole('dialog')
    expect(within(details).getByText(uk.sync.details.serverOffset)).toBeInTheDocument()
    expect(within(details).getByText(uk.sync.details.openPositions)).toBeInTheDocument()
  })

  it('chips still render when the accounts list fails', async () => {
    mockApi(
      http.get('/api/sync/status', () => HttpResponse.json({ items: [row({ error_code: 'timeout' })] })),
      http.get('/api/accounts', () => HttpResponse.json({ error: { code: 'internal_error', message: 'x' } }, { status: 500 })),
    )
    renderWithProviders(<SyncChips />)
    expect(await screen.findByRole('button', { name: `CT Demo: ${uk.sync.timeoutUnknownPlatform}` })).toBeInTheDocument()
  })
})

describe('syncErrorText', () => {
  const WORKER_CODES = [
    'not_configured', 'token_expired', 'token_invalid', 'token_store_failed', 'not_authorized', 'client_auth_failed',
    'connection_failed', 'rate_limited', 'bad_response', 'account_disconnected', 'equity_unavailable', 'internal_error', 'timeout',
    'history_incomplete',
  ] as const

  it.each(WORKER_CODES)('cTrader %s uses the cTrader text', (code) => {
    expect(syncErrorText(code, 'ctrader')).toBe(uk.ctrader.errors[code])
  })

  it('shared codes keep the MT5 text on an MT5 account', () => {
    expect(syncErrorText('timeout', 'mt5')).toBe(uk.sync.errors.timeout)
    expect(syncErrorText('internal_error', 'mt5')).toBe(uk.sync.errors.internal_error)
  })

  it('an unknown code is never shown raw', () => {
    expect(syncErrorText('brand_new_code', 'ctrader')).toBe(uk.sync.errors.unknown)
  })
})
