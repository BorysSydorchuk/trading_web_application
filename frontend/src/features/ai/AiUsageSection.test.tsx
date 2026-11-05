import { screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { formatDateTimeBrussels } from '@/lib/time'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { AiUsageSection } from './AiUsageSection'

const t = uk.aiSettings
const k = uk.aiKey

const CHECKED_BEFORE = '2026-11-05T08:00:00Z'
const CHECKED_AFTER = '2026-11-05T09:30:00Z'

function usage(extra: Record<string, unknown> = {}) {
  return {
    month: '2026-11',
    cost_usd: '0.12',
    calls: 3,
    failed_calls: 0,
    unpriced_calls: 0,
    input_tokens: 100,
    output_tokens: 50,
    configured: true,
    extraction_model: 'claude-test',
    ...extra,
  }
}

function health(ai?: { state: string; checked_at: string | null }) {
  return {
    status: 'ok',
    version: '0.1.0',
    time_utc: '2026-11-05T10:00:00Z',
    db: { ok: true, latency_ms: 2, error: null },
    ...(ai ? { ai } : {}),
  }
}

/** The key starts invalid; POST /api/ai/check "fixes" it (as after a restart with a new key). */
function serveKeyCheck() {
  let ai = { state: 'invalid_key', checked_at: CHECKED_BEFORE }
  const posts: number[] = []
  mockApi(
    http.get('/api/health', () => HttpResponse.json(health(ai))),
    http.get('/api/ai/usage', () => HttpResponse.json(usage({ key_state: ai.state }))),
    http.post('/api/ai/check', () => {
      posts.push(Date.now())
      ai = { state: 'ok', checked_at: CHECKED_AFTER }
      return HttpResponse.json(ai)
    }),
  )
  return posts
}

describe('AiUsageSection: key state', () => {
  it('shows the invalid key state, its hint and the check time in Brussels', async () => {
    serveKeyCheck()
    renderWithProviders(<AiUsageSection />)

    expect(await screen.findByText(k.states.invalid_key)).toBeInTheDocument()
    expect(await screen.findByText(formatDateTimeBrussels(CHECKED_BEFORE))).toBeInTheDocument()
    expect(screen.getByText(k.hints.invalid_key.title)).toBeInTheDocument()
    // Only the state speaks: no "configured" next to an invalid key.
    expect(screen.queryByText(t.configured)).not.toBeInTheDocument()
  })

  it('"Перевірити ключ" posts the check and shows the new state', async () => {
    const posts = serveKeyCheck()
    const { user } = renderWithProviders(<AiUsageSection />)

    await user.click(await screen.findByRole('button', { name: t.checkKey }))

    expect(await screen.findByText(k.states.ok)).toBeInTheDocument()
    expect(posts).toHaveLength(1)
    expect(await screen.findByText(formatDateTimeBrussels(CHECKED_AFTER))).toBeInTheDocument()
    expect(screen.queryByText(k.hints.invalid_key.title)).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: t.checkKey })).toBeEnabled())
  })

  it('shows "перевіряється…" while the server is checking', async () => {
    mockApi(
      http.get('/api/health', () => HttpResponse.json(health({ state: 'checking', checked_at: null }))),
      http.get('/api/ai/usage', () => HttpResponse.json(usage({ key_state: 'checking' }))),
    )
    renderWithProviders(<AiUsageSection />)

    expect(await screen.findByText('перевіряється…')).toBeInTheDocument()
    expect(screen.queryByText(t.checkedAt)).not.toBeInTheDocument()
  })

  it('shows one "not set" message for not_configured', async () => {
    mockApi(
      http.get('/api/health', () => HttpResponse.json(health({ state: 'not_configured', checked_at: null }))),
      http.get('/api/ai/usage', () =>
        HttpResponse.json(usage({ configured: false, key_state: 'not_configured' })),
      ),
    )
    renderWithProviders(<AiUsageSection />)

    expect(await screen.findByText(k.states.not_configured)).toBeInTheDocument()
    expect(screen.getByText(k.hints.not_configured.title)).toBeInTheDocument()
    expect(screen.queryByText(t.notConfigured)).not.toBeInTheDocument()
    expect(screen.queryByText(t.notConfiguredShort)).not.toBeInTheDocument()
  })

  it('falls back to the "configured" line and hides the check for an older backend', async () => {
    mockApi(
      http.get('/api/health', () => HttpResponse.json(health())),
      http.get('/api/ai/usage', () => HttpResponse.json(usage({ configured: false }))),
    )
    renderWithProviders(<AiUsageSection />)

    expect(await screen.findByText(t.notConfiguredShort)).toBeInTheDocument()
    expect(screen.getByText(t.notConfigured)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t.checkKey })).not.toBeInTheDocument()
  })
})
