import { act, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels, formatTimeBrussels } from '@/lib/time'
import { CalculatorPage } from '@/pages/CalculatorPage'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { marginRequest, NO_MARGIN, result } from './calculator.fixture'
import type { CalculateResult, MarginRequest } from './types'
import { MARGIN_MAX_POLLS, MARGIN_POLL_MS } from './useLiveMargin'
import { fillForm, input, f, r, rowValue, serveSetup, submit } from './testUtils'

// Only the polling interval runs on a fake clock; network, React and user-event stay real.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
})
afterEach(() => {
  vi.useRealTimers()
})

/** Lets pending responses settle (real time), then moves the poll clock one interval. */
async function nextPoll(settleMs = 10) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, settleMs))
    vi.advanceTimersByTime(MARGIN_POLL_MS)
    await new Promise((resolve) => setTimeout(resolve, settleMs))
  })
}

interface Served {
  posts: number
  gets: number
}

/** Calculate answers `calc`; the margin POST answers pending; GETs answer `answers` in order (last repeats). */
function serveMargin(answers: MarginRequest[], calc: CalculateResult = result()): Served {
  const served: Served = { posts: 0, gets: 0 }
  mockApi(
    http.post('/api/calculator/calculate', () => HttpResponse.json(calc)),
    http.post('/api/calculator/margin-requests', () => {
      served.posts += 1
      return HttpResponse.json(marginRequest(), { status: 202 })
    }),
    http.get('/api/calculator/margin-requests/:id', () => {
      const answer = answers[Math.min(served.gets, answers.length - 1)]
      served.gets += 1
      return HttpResponse.json(answer)
    }),
  )
  return served
}

async function calculate() {
  serveSetup()
  const view = renderWithProviders(<CalculatorPage />, { path: '/calculator' })
  await fillForm(view.user)
  await submit(view.user)
  await screen.findByRole('region', { name: r.title })
  return view
}

const DONE = marginRequest({ status: 'done', source: 'mt5', amount: '5300.00', finished_at: '2026-11-10T08:00:03Z' })

describe('CalculatorForm live margin', () => {
  it('shows «обчислюється…» while pending/processing, then the live MT5 margin, then stops polling', async () => {
    const served = serveMargin([marginRequest(), marginRequest({ status: 'processing' }), DONE])
    const { unmount } = await calculate()
    expect(within(rowValue(r.margin)).getByText(r.marginPending)).toBeInTheDocument()
    await nextPoll()
    expect(served).toEqual({ posts: 1, gets: 1 })
    expect(within(rowValue(r.margin)).getByText(r.marginPending)).toBeInTheDocument()
    await nextPoll()
    await nextPoll()
    expect(served.gets).toBe(3)
    expect(within(rowValue(r.margin)).getByText('5 300.00 USD')).toBeInTheDocument()
    expect(within(rowValue(r.margin)).getByText(r.marginLive(formatTimeBrussels(new Date('2026-11-10T08:00:03Z'))))).toBeInTheDocument()
    await nextPoll()
    expect(served.gets).toBe(3)
    unmount()
  })

  it('falls back to the labelled cached estimate when MT5 fails', async () => {
    serveMargin([marginRequest({ status: 'failed', error_code: 'terminal_unreachable' })])
    await calculate()
    await nextPoll()
    const margin = rowValue(r.margin)
    expect(within(margin).getByText('5 301.00 USD')).toBeInTheDocument()
    expect(within(margin).getByText(r.marginEstimate(formatDateTimeBrussels('2026-11-09T09:00:00Z'), '2640.00', '1.00'))).toBeInTheDocument()
    expect(within(margin).getByText(r.marginLiveFailed.failed)).toBeInTheDocument()
    // The sizing result stays.
    expect(rowValue(r.volume)).toHaveTextContent('2.00')
  })

  it.each([
    ['login_failed', r.marginFailedWith(uk.sync.errors.login_failed)],
    ['terminal_not_found', r.marginFailedWith(uk.sync.errors.terminal_not_found)],
    ['timeout', r.marginFailedWith(uk.sync.errors.timeout)],
    ['interrupted', r.marginErrorCodes.interrupted],
    ['internal_error', r.marginErrorCodes.internal_error],
    ['something_new', r.marginLiveFailed.failed],
  ])('names the MT5 failure %s next to the estimate', async (code, text) => {
    serveMargin([marginRequest({ status: 'failed', error_code: code })])
    await calculate()
    await nextPoll()
    const margin = rowValue(r.margin)
    expect(within(margin).getByText('5 301.00 USD')).toBeInTheDocument()
    expect(within(margin).getByText(text)).toBeInTheDocument()
  })

  it('gives up after MARGIN_MAX_POLLS pending answers and shows the expired fallback', async () => {
    const served = serveMargin([marginRequest()], result({ margin: NO_MARGIN }))
    await calculate()
    for (let i = 0; i < MARGIN_MAX_POLLS; i++) await nextPoll(1)
    expect(served.gets).toBe(MARGIN_MAX_POLLS)
    expect(within(rowValue(r.margin)).getByText(r.marginUnavailable)).toBeInTheDocument()
    expect(within(rowValue(r.margin)).getByText(r.marginLiveFailed.expired)).toBeInTheDocument()
    await nextPoll()
    await nextPoll()
    expect(served.gets).toBe(MARGIN_MAX_POLLS)
  })

  it('shows «маржа недоступна» when the request expires and there is no estimate', async () => {
    serveMargin([marginRequest({ status: 'expired', error_code: 'request_expired' })], result({ margin: NO_MARGIN }))
    await calculate()
    await nextPoll()
    expect(within(rowValue(r.margin)).getByText(r.marginUnavailable)).toBeInTheDocument()
    expect(within(rowValue(r.margin)).getByText(r.marginLiveFailed.expired)).toBeInTheDocument()
  })

  it('falls back when the margin request itself fails, keeping the sizing result', async () => {
    mockApi(
      http.post('/api/calculator/calculate', () => HttpResponse.json(result())),
      http.post('/api/calculator/margin-requests', () => HttpResponse.json({ error: { code: 'internal_error', message: 'x' } }, { status: 500 })),
    )
    await calculate()
    expect(await within(rowValue(r.margin)).findByText(r.marginLiveFailed.error)).toBeInTheDocument()
    expect(rowValue(r.volume)).toHaveTextContent('2.00')
  })

  it('discards an in-flight margin answer after a new calculate', async () => {
    let release!: () => void
    const held = new Promise<void>((resolve) => { release = resolve })
    let posts = 0
    mockApi(
      http.post('/api/calculator/calculate', () => HttpResponse.json(result())),
      http.post('/api/calculator/margin-requests', () => {
        posts += 1
        // First job polls (and is held); the second answers done at once with another amount.
        return posts === 1
          ? HttpResponse.json(marginRequest(), { status: 202 })
          : HttpResponse.json(marginRequest({ id: 42, status: 'done', source: 'mt5', amount: '1111.00' }), { status: 202 })
      }),
      http.get('/api/calculator/margin-requests/:id', async () => {
        await held
        return HttpResponse.json(marginRequest({ status: 'done', source: 'mt5', amount: '9999.00' }))
      }),
    )
    const { user } = await calculate()
    await nextPoll()
    await submit(user)
    expect(await within(rowValue(r.margin)).findByText('1 111.00 USD')).toBeInTheDocument()
    release()
    await nextPoll()
    expect(screen.queryByText('9 999.00 USD')).not.toBeInTheDocument()
    expect(within(rowValue(r.margin)).getByText('1 111.00 USD')).toBeInTheDocument()
  })

  it('discards the margin when an input changes and stops polling on unmount', async () => {
    const served = serveMargin([marginRequest(), DONE])
    const { user, unmount } = await calculate()
    await user.type(input(f.entry), '5')
    expect(screen.queryByRole('region', { name: r.title })).not.toBeInTheDocument()
    await nextPoll()
    await nextPoll()
    expect(served.gets).toBe(0)
    expect(screen.queryByText('5 300.00 USD')).not.toBeInTheDocument()
    unmount()
    await nextPoll()
    expect(served.gets).toBe(0)
  })

  it('stops polling on unmount while the request is pending', async () => {
    const served = serveMargin([marginRequest()])
    const { unmount } = await calculate()
    await nextPoll()
    expect(served.gets).toBe(1)
    unmount()
    await nextPoll()
    await nextPoll()
    expect(served.gets).toBe(1)
  })
})
