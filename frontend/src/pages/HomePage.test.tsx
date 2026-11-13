import { act, screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Sidebar } from '@/components/layout/Sidebar'
import { biasKeys, invalidateAfterWrite } from '@/features/bias/api'
import type { BiasStatus } from '@/features/bias/types'
import { account, spec } from '@/features/calculator/calculator.fixture'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { emptyDashboard } from '@/features/dashboard/dashboard.fixture'
import { HomePage } from './HomePage'

const t = uk.bias.status

function status(overrides: Partial<BiasStatus> = {}): BiasStatus {
  return {
    date: '2026-11-06', weekday: true, now: '2026-11-06T11:30:00Z',
    sessions: {
      pre_london: { note_id: 7, missing: false, remind: false, from: '07:45', until: '11:00' },
      pre_ny: { note_id: null, missing: true, remind: true, from: '12:30', until: '16:00' },
    },
    weekly: { note_id: 8 }, monthly: { note_id: null }, ...overrides,
  }
}

// The dashboard widgets on Home load their own endpoints; these tests serve them empty.
beforeEach(() => mockApi(
  http.get('/api/dashboard', () => HttpResponse.json(emptyDashboard())),
  http.get('/api/digests/suggestion', () => HttpResponse.json({ weekly: null, monthly: null })),
  http.get('/api/sync/status', () => HttpResponse.json({ items: [] })),
))

function serveSidebar() {
  mockApi(http.get('/api/inbox/counts', () => HttpResponse.json({ needs_sl: 0, needs_description: 0, draft: 0 })))
}

describe('HomePage bias status', () => {
  // The calculator panel on Home loads the accounts list; these tests are about bias status only.
  beforeEach(() => mockApi(http.get('/api/accounts', () => HttpResponse.json({ items: [] }))))

  it('shows all periods, server reminders and links with the server Brussels date', async () => {
    mockApi(http.get('/api/bias/status', () => HttpResponse.json(status())))
    renderWithProviders(<HomePage />)
    expect(await screen.findByText(t.date('2026-11-06'))).toBeInTheDocument()
    const london = screen.getByRole('article', { name: uk.bias.kinds.pre_london })
    expect(within(london).getByRole('link', { name: t.open })).toHaveAttribute('href', '/bias/7')
    const ny = screen.getByRole('article', { name: uk.bias.kinds.pre_ny })
    expect(within(ny).getByText(t.reminder(uk.bias.kinds.pre_ny))).toBeInTheDocument()
    expect(within(ny).getByRole('link', { name: t.record })).toHaveAttribute('href', '/bias/new?kind=pre_ny&date=2026-11-06')
    expect(within(screen.getByRole('article', { name: uk.bias.kinds.weekly })).getByRole('link', { name: t.open })).toHaveAttribute('href', '/bias/8')
    expect(within(screen.getByRole('article', { name: uk.bias.kinds.monthly })).getByRole('link', { name: t.record })).toHaveAttribute('href', '/bias/new?kind=monthly&date=2026-11-06')
    expect(within(london).queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows loading, reports failure, and retries successfully', async () => {
    let release!: () => void
    const pending = new Promise<void>((resolve) => { release = resolve })
    mockApi(http.get('/api/bias/status', async () => {
      await pending
      return HttpResponse.json({ error: { code: 'config_error', message: 'Broken config' } }, { status: 500 })
    }))
    const { user } = renderWithProviders(<HomePage />)
    expect(screen.getByText(t.loading)).toBeInTheDocument()
    release()
    expect(await screen.findByText(t.loadError)).toBeInTheDocument()
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
    mockApi(http.get('/api/bias/status', () => HttpResponse.json(status())))
    await user.click(screen.getByRole('button', { name: uk.common.retry }))
    expect(await screen.findByRole('article', { name: uk.bias.kinds.pre_ny })).toBeInTheDocument()
    expect(screen.queryByText(t.loadError)).not.toBeInTheDocument()
  })

  it('trusts remind=false for missing weekend sessions without browser time calculations', async () => {
    const data = status({ date: '2026-11-07', weekday: false })
    data.sessions.pre_london = { ...data.sessions.pre_london, note_id: null, missing: true }
    data.sessions.pre_ny.remind = false
    mockApi(http.get('/api/bias/status', () => HttpResponse.json(data)))
    renderWithProviders(<HomePage />)
    await screen.findByText(t.date(data.date))
    expect(screen.getAllByText(t.missing)).toHaveLength(3)
    expect(screen.queryByText(t.reminder(uk.bias.kinds.pre_london))).not.toBeInTheDocument()
    expect(screen.queryByText(t.reminder(uk.bias.kinds.pre_ny))).not.toBeInTheDocument()
  })

  it('refreshes dashboard and sidebar together after a note write, clearing the reminder badge', async () => {
    serveSidebar()
    let data = status()
    let requests = 0
    mockApi(http.get('/api/bias/status', () => { requests += 1; return HttpResponse.json(data) }))
    const { queryClient } = renderWithProviders(<><Sidebar /><HomePage /></>)
    expect(await screen.findByLabelText(t.badge(1))).toHaveTextContent('1')
    expect(requests).toBe(1)
    data = status()
    data.sessions.pre_ny = { ...data.sessions.pre_ny, note_id: 9, missing: false, remind: false }
    await act(async () => { await invalidateAfterWrite(queryClient) })
    await waitFor(() => expect(screen.queryByLabelText(t.badge(1))).not.toBeInTheDocument())
    expect(within(screen.getByRole('article', { name: uk.bias.kinds.pre_ny })).getByRole('link', { name: t.open })).toHaveAttribute('href', '/bias/9')
    expect(requests).toBe(2)
  })

  it('polls the server after 60 seconds and reveals a newly due reminder', async () => {
    let data = status()
    data.sessions.pre_ny.remind = false
    let requests = 0
    mockApi(http.get('/api/bias/status', () => { requests += 1; return HttpResponse.json(data) }))
    const { unmount } = renderWithProviders(<HomePage />)
    await screen.findByText(t.date(data.date))
    expect(screen.queryByText(t.reminder(uk.bias.kinds.pre_ny))).not.toBeInTheDocument()
    // Keep network and React scheduling real; advance only the polling interval's clock.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    try {
      // Remount so the query observer schedules its polling timer on the controlled clock.
      unmount()
      const mounted = renderWithProviders(<HomePage />)
      await screen.findByText(t.date(data.date))
      const before = requests
      data = status()
      await act(async () => { vi.advanceTimersByTime(60_000) })
      expect(await screen.findByText(t.reminder(uk.bias.kinds.pre_ny))).toBeInTheDocument()
      expect(requests).toBe(before + 1)
      mounted.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('replaces a stale reminder badge with an unavailable indicator after refresh fails', async () => {
    serveSidebar()
    mockApi(http.get('/api/bias/status', () => HttpResponse.json(status())))
    const { queryClient } = renderWithProviders(<><Sidebar /><HomePage /></>)
    await screen.findByLabelText(t.badge(1))
    mockApi(http.get('/api/bias/status', () => HttpResponse.json({}, { status: 500 })))
    await act(async () => { await queryClient.invalidateQueries({ queryKey: biasKeys.status }) })
    expect(await screen.findByLabelText(t.loadError)).toHaveTextContent(t.unavailable)
    expect(screen.queryByLabelText(t.badge(1))).not.toBeInTheDocument()
    expect(screen.queryByRole('article')).not.toBeInTheDocument()
    expect(screen.getByText(t.loadError)).toBeInTheDocument()
  })
})

describe('HomePage calculator panel', () => {
  it('renders the compact calculator with a link to the full page', async () => {
    mockApi(
      http.get('/api/bias/status', () => HttpResponse.json(status())),
      http.get('/api/accounts', () => HttpResponse.json({ items: [account()] })),
      http.get('/api/accounts/:id/symbol-specs', () => HttpResponse.json({ items: [spec()], missing: [] })),
    )
    renderWithProviders(<HomePage />)
    const panel = await screen.findByRole('region', { name: uk.calculator.home.title })
    expect(within(panel).getByRole('link', { name: uk.calculator.home.openFull })).toHaveAttribute('href', '/calculator')
    expect(await within(panel).findByRole('option', { name: 'XAUUSD' })).toBeInTheDocument()
    expect(within(panel).getByRole('form', { name: uk.calculator.form.label })).toBeInTheDocument()
    expect(within(panel).getByRole('button', { name: uk.calculator.form.submit })).toBeEnabled()
  })
})
