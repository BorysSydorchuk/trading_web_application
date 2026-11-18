import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { DesktopSection } from './DesktopSection'

const t = uk.desktopSettings

describe('DesktopSection (M8-12)', () => {
  it('shows both switches and saves «Запускати з Windows»', async () => {
    const sent: unknown[] = []
    mockApi(
      http.get('/api/system/desktop', () => HttpResponse.json({ supported: true, autostart: true, terminals_visible: false })),
      http.put('/api/system/autostart', async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json({ supported: true, autostart: false, terminals_visible: false })
      }),
    )
    const { user } = renderWithProviders(<DesktopSection />)

    const autostart = await screen.findByRole('checkbox', { name: new RegExp(t.autostart) })
    expect(autostart).toBeChecked()
    expect(screen.getByRole('checkbox', { name: new RegExp(t.terminals) })).not.toBeChecked()

    await user.click(autostart)

    expect(sent).toEqual([{ enabled: false }])
    expect(await screen.findByRole('checkbox', { name: new RegExp(t.autostart) })).not.toBeChecked()
  })

  it('shows a readable error when the shortcut cannot be written', async () => {
    mockApi(
      http.get('/api/system/desktop', () => HttpResponse.json({ supported: true, autostart: false, terminals_visible: false })),
      http.put('/api/system/autostart', () =>
        HttpResponse.json({ error: { code: 'shortcut_failed', message: 'access denied' } }, { status: 500 }),
      ),
    )
    const { user } = renderWithProviders(<DesktopSection />)

    await user.click(await screen.findByRole('checkbox', { name: new RegExp(t.autostart) }))

    expect(await screen.findByRole('alert')).toHaveTextContent(t.saveError)
  })

  it('explains that it is Windows only', async () => {
    mockApi(http.get('/api/system/desktop', () => HttpResponse.json({ supported: false, autostart: false, terminals_visible: false })))
    renderWithProviders(<DesktopSection />)
    expect(await screen.findByText(t.unsupported)).toBeInTheDocument()
  })
})
