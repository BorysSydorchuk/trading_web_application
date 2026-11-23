import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { account as mt5Account } from '@/features/calculator/calculator.fixture'
import { navigateToAuthorizeUrl } from '@/features/ctrader/navigation'
import type { CtraderAccountItem, CtraderStatus } from '@/features/ctrader/types'
import { uk } from '@/i18n/uk'
import { errorText } from '@/lib/errors'
import { ApiError } from '@/api/client'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { AccountsSection } from './AccountsSection'
import type { Account } from './types'

vi.mock('@/features/ctrader/navigation', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/ctrader/navigation')>()),
  navigateToAuthorizeUrl: vi.fn(),
}))

const c = uk.ctrader
const f = uk.accounts.form

const CONNECTED: CtraderStatus = { configured: true, connected: true, error_code: null }
const FREE: CtraderAccountItem = { ctid_trader_account_id: 7001, is_live: false, trader_login: 5100200, broker: 'Broker One', already_added: false }
const ADDED: CtraderAccountItem = { ctid_trader_account_id: 7002, is_live: true, trader_login: 5100300, broker: 'Broker Two', already_added: true }

const ctraderAccount = (): Account =>
  mt5Account({ id: 2, platform: 'ctrader', name: 'CT Demo', login: 5100200, server: 'Broker One', password_env_key: '', password_configured: true })

function serve(status: CtraderStatus, accounts: Account[] = [mt5Account()], items: CtraderAccountItem[] = [FREE, ADDED]) {
  mockApi(
    http.get('/api/accounts', () => HttpResponse.json({ items: accounts })),
    http.get('/api/ctrader/status', () => HttpResponse.json(status)),
    http.get('/api/ctrader/accounts', () => HttpResponse.json({ items })),
  )
}

async function openCtrader(user: ReturnType<typeof renderWithProviders>['user']) {
  await user.click(await screen.findByRole('button', { name: uk.accounts.add }))
  await user.click(await screen.findByRole('button', { name: new RegExp(`^${c.platform.ctrader}`) }))
}

async function fillJournalFields(user: ReturnType<typeof renderWithProviders>['user']) {
  await user.type(screen.getByLabelText(new RegExp(`^${f.fields.name}`)), 'CT Demo')
  await user.type(screen.getByLabelText(new RegExp(`^${f.fields.firm}`)), 'Firm')
  await user.type(screen.getByLabelText(new RegExp(`^${f.fields.program}`)), 'Program')
  await user.selectOptions(screen.getByLabelText(new RegExp(`^${f.fields.phase}`)), 'phase_1')
  await user.type(screen.getByLabelText(new RegExp(`^${f.fields.starting_balance}`)), '10000')
}

beforeEach(() => {
  vi.mocked(navigateToAuthorizeUrl).mockClear()
})

describe('Add account: platform choice', () => {
  it('asks for the platform first', async () => {
    serve(CONNECTED)
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await user.click(await screen.findByRole('button', { name: uk.accounts.add }))
    const group = await screen.findByRole('group', { name: c.platform.legend })
    expect(within(group).getByRole('button', { name: new RegExp(`^${c.platform.mt5}`) })).toBeInTheDocument()
    expect(within(group).getByRole('button', { name: new RegExp(`^${c.platform.ctrader}`) })).toBeInTheDocument()
  })

  it('MT5 path: the same form and POST /api/accounts with login, server and path', async () => {
    serve(CONNECTED)
    let body: Record<string, unknown> | null = null
    mockApi(
      http.post('/api/accounts', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(mt5Account({ id: 9 }), { status: 201 })
      }),
    )
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await user.click(await screen.findByRole('button', { name: uk.accounts.add }))
    await user.click(await screen.findByRole('button', { name: new RegExp(`^${c.platform.mt5}`) }))

    expect(await screen.findByRole('heading', { name: f.createTitle })).toBeInTheDocument()
    await fillJournalFields(user)
    await user.type(screen.getByLabelText(new RegExp(`^${f.fields.login}`)), '1234567')
    await user.type(screen.getByLabelText(new RegExp(`^${f.fields.server}`)), 'FN-Server')
    await user.type(screen.getByLabelText(new RegExp(`^${f.fields.terminal_path}`)), 'D:\\MT5\\a\\terminal64.exe')
    await user.click(screen.getByRole('button', { name: f.submitCreate }))

    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ login: 1234567, server: 'FN-Server', terminal_path: 'D:\\MT5\\a\\terminal64.exe', name: 'CT Demo' })
    expect(body).not.toHaveProperty('ctid_trader_account_id')
  })
})

describe('Add account: cTrader states', () => {
  it('not configured: names both .env keys and offers no connect button', async () => {
    serve({ configured: false, connected: false, error_code: 'not_configured' })
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await openCtrader(user)
    expect(await screen.findByText(c.flow.notConfiguredTitle)).toBeInTheDocument()
    expect(screen.getByText(c.flow.envClientId)).toBeInTheDocument()
    expect(screen.getByText(c.flow.envClientSecret)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: c.flow.connect })).not.toBeInTheDocument()
  })

  it('not connected: the button goes to authorize_url', async () => {
    serve({ configured: true, connected: false, error_code: null })
    const url = 'https://id.ctrader.com/my/settings/openapi/grantingaccess/?x=1'
    mockApi(http.post('/api/ctrader/connect', () => HttpResponse.json({ authorize_url: url })))
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await openCtrader(user)
    await user.click(await screen.findByRole('button', { name: c.flow.connect }))
    await waitFor(() => expect(navigateToAuthorizeUrl).toHaveBeenCalledWith(url))
  })

  it('refuses a non-https authorize_url', async () => {
    serve({ configured: true, connected: false, error_code: null })
    mockApi(http.post('/api/ctrader/connect', () => HttpResponse.json({ authorize_url: 'javascript:alert(1)' })))
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await openCtrader(user)
    await user.click(await screen.findByRole('button', { name: c.flow.connect }))
    await waitFor(() => expect(screen.getByRole('button', { name: c.flow.connect })).toBeEnabled())
    expect(navigateToAuthorizeUrl).not.toHaveBeenCalled()
  })

  it.each(['token_expired', 'token_invalid'] as const)('%s: says to connect again', async (code) => {
    serve({ configured: true, connected: false, error_code: code })
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await openCtrader(user)
    expect(await screen.findByText(/Підключіть cTrader знову/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: c.flow.connect })).toBeInTheDocument()
  })

  it('connected: an added account is disabled; the form has no MT5 fields; POST has only the contract keys', async () => {
    serve(CONNECTED)
    let body: Record<string, unknown> | null = null
    mockApi(
      http.post('/api/ctrader/accounts', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(ctraderAccount(), { status: 201 })
      }),
    )
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await openCtrader(user)

    const radios = await screen.findAllByRole('radio')
    expect(radios[0]).toBeEnabled()
    expect(radios[1]).toBeDisabled()
    expect(screen.getByText(c.flow.alreadyAdded)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: c.flow.next })).toBeDisabled()

    await user.click(radios[0] as HTMLElement)
    await user.click(screen.getByRole('button', { name: c.flow.next }))

    expect(await screen.findByLabelText(new RegExp(`^${f.fields.name}`))).toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${f.fields.login}`))).not.toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${f.fields.server}`))).not.toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${f.fields.terminal_path}`))).not.toBeInTheDocument()

    await fillJournalFields(user)
    await user.click(screen.getByRole('button', { name: f.submitCreate }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toMatchObject({ ctid_trader_account_id: 7001, name: 'CT Demo', phase: 'phase_1', starting_balance: '10000' })
    for (const key of ['login', 'server', 'terminal_path', 'platform']) expect(body).not.toHaveProperty(key)
  })
})

describe('OAuth return', () => {
  it('success: message, the cTrader step reopens, the query string is cleaned', async () => {
    serve(CONNECTED)
    const { router } = renderWithProviders(<AccountsSection />, { path: '/settings', url: '/settings?ctrader=connected&keep=1' })
    expect(await screen.findByText(c.oauth.connected)).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: c.flow.title })).toBeInTheDocument()
    expect(await screen.findAllByRole('radio')).toHaveLength(2)
    await waitFor(() => expect(router.state.location.search).toBe('?keep=1'))
  })

  it('error: Ukrainian text, no dialog, the query string is cleaned', async () => {
    serve({ configured: true, connected: false, error_code: null })
    const { router } = renderWithProviders(<AccountsSection />, { path: '/settings', url: '/settings?ctrader_error=access_denied' })
    expect(await screen.findByText(c.errors.access_denied)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => expect(router.state.location.search).toBe(''))
  })

  it('an unknown code never shows raw', async () => {
    serve({ configured: true, connected: false, error_code: null })
    renderWithProviders(<AccountsSection />, { path: '/settings', url: '/settings?ctrader_error=%3Cb%3Eraw' })
    expect(await screen.findByText(c.errors.unknown)).toBeInTheDocument()
    expect(screen.queryByText(/raw/)).not.toBeInTheDocument()
  })
})

describe('Accounts table and disconnect', () => {
  it('shows the platform; a cTrader row has no password state; editing has no login, server or path', async () => {
    serve(CONNECTED, [mt5Account(), ctraderAccount()])
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    const row = (await screen.findByText('CT Demo')).closest('tr') as HTMLElement
    expect(within(row).getByText(uk.accounts.platform.ctrader)).toBeInTheDocument()
    expect(within(row).queryByText(uk.accounts.password.configured)).not.toBeInTheDocument()
    expect(within(row).queryByText(uk.accounts.password.keyLabel, { exact: false })).not.toBeInTheDocument()

    await user.click(within(row).getByRole('button', { name: `${uk.accounts.actions.edit}: CT Demo` }))
    expect(await screen.findByRole('heading', { name: f.editTitle })).toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${f.fields.login}`))).not.toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${f.fields.server}`))).not.toBeInTheDocument()
    expect(screen.queryByLabelText(new RegExp(`^${f.fields.terminal_path}`))).not.toBeInTheDocument()
  })

  it('saving an edit never sends login, server or path, even if the broker title has outer spaces', async () => {
    const stored = { ...ctraderAccount(), server: ' Broker One ' }
    serve(CONNECTED, [stored])
    let body: Record<string, unknown> | null = null
    mockApi(
      http.patch('/api/accounts/2', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(stored)
      }),
    )
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await user.click(await screen.findByRole('button', { name: `${uk.accounts.actions.edit}: CT Demo` }))
    await user.type(await screen.findByLabelText(new RegExp(`^${f.fields.firm}`)), ' X')
    await user.click(screen.getByRole('button', { name: f.submitEdit }))
    await waitFor(() => expect(body).not.toBeNull())
    expect(body).toEqual({ firm: 'FundedNext X' })
  })

  it('disconnect asks first, then calls DELETE', async () => {
    serve(CONNECTED)
    let deleted = 0
    mockApi(
      http.delete('/api/ctrader/connection', () => {
        deleted += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { user } = renderWithProviders(<AccountsSection />, { path: '/settings' })
    await user.click(await screen.findByRole('button', { name: c.disconnect.action }))
    expect(await screen.findByRole('heading', { name: c.disconnect.title })).toBeInTheDocument()
    expect(deleted).toBe(0)
    await user.click(screen.getByRole('button', { name: c.disconnect.confirm }))
    expect(await screen.findByText(c.disconnect.done)).toBeInTheDocument()
    expect(deleted).toBe(1)
  })

  it('no stored connection: no disconnect action', async () => {
    serve({ configured: true, connected: false, error_code: null })
    renderWithProviders(<AccountsSection />, { path: '/settings' })
    await screen.findByText(mt5Account().name)
    expect(screen.queryByRole('button', { name: c.disconnect.action })).not.toBeInTheDocument()
  })
})

describe('cTrader API error text', () => {
  const CODES = [
    'not_configured', 'token_expired', 'token_invalid', 'token_store_failed', 'not_authorized', 'client_auth_failed',
    'connection_failed', 'timeout', 'rate_limited', 'trade_scope_refused', 'bad_response', 'account_disconnected',
    'equity_unavailable', 'state_invalid', 'access_denied', 'internal_error', 'account_not_granted', 'account_incomplete',
  ] as const

  it.each(CODES)('ctrader_%s has its own Ukrainian text', (code) => {
    const text = errorText(new ApiError(`ctrader_${code}`, 'raw english', 502))
    expect(text).toBe(c.errors[code])
    expect(text).not.toContain('raw english')
  })

  it('an unknown ctrader code gets the generic text', () => {
    expect(errorText(new ApiError('ctrader_new_code', 'raw english', 502))).toBe(c.errors.unknown)
  })
})
