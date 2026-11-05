import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { StatusBar } from './StatusBar'

const chip = uk.aiKey.chip

function health(ai?: { state: string; checked_at: string | null }) {
  return {
    status: 'ok',
    version: '0.1.0',
    time_utc: '2026-11-05T10:00:00Z',
    db: { ok: true, latency_ms: 2, error: null },
    ...(ai ? { ai } : {}),
  }
}

function serve(body: ReturnType<typeof health>) {
  mockApi(
    http.get('/api/health', () => HttpResponse.json(body)),
    http.get('/api/sync/status', () => HttpResponse.json({ items: [] })),
  )
}

const ALL_CHIP_TEXTS = [chip.invalid_key, chip.not_configured, chip.unreachable]

describe('StatusBar: AI key chip', () => {
  it.each([
    ['invalid_key', chip.invalid_key, chip.invalid_keyHint],
    ['not_configured', chip.not_configured, chip.not_configuredHint],
    ['unreachable', chip.unreachable, chip.unreachableHint],
  ])('shows the chip with a hint for %s', async (state, text, hint) => {
    serve(health({ state, checked_at: '2026-11-05T09:59:00Z' }))
    renderWithProviders(<StatusBar />)

    const label = await screen.findByText(text)
    expect(label.closest('[title]')).toHaveAttribute('title', hint)
    // The server/DB state stays green: an AI problem does not degrade it.
    expect(screen.getByText(uk.statusBar.ok)).toBeInTheDocument()
  })

  it.each(['ok', 'checking'])('shows no AI chip for %s', async (state) => {
    serve(health({ state, checked_at: null }))
    renderWithProviders(<StatusBar />)

    expect(await screen.findByText(uk.statusBar.ok)).toBeInTheDocument()
    for (const text of ALL_CHIP_TEXTS) expect(screen.queryByText(text)).not.toBeInTheDocument()
  })

  it('shows no AI chip when an older backend sends no ai object', async () => {
    serve(health())
    renderWithProviders(<StatusBar />)

    expect(await screen.findByText(uk.statusBar.ok)).toBeInTheDocument()
    for (const text of ALL_CHIP_TEXTS) expect(screen.queryByText(text)).not.toBeInTheDocument()
  })
})
