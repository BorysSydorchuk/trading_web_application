import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { parseSynonyms } from './api'
import { EmotionsSection } from './EmotionsSection'
import { OptionListEditor } from './OptionListEditor'

const t = uk.journalOptions
const URL = '/api/journal-options/emotion_before'
const OPTIONS = [
  { value: 'calm', label: 'спокій', hidden: false, synonyms: ['calm'], used_count: 3 },
  { value: 'anxiety', label: 'тривога', hidden: false, synonyms: [], used_count: 0 },
]
const listed = () => HttpResponse.json({ field: 'emotion_before', options: OPTIONS })

describe('Settings «Емоції»', () => {
  it('shows both lists', async () => {
    mockApi(
      http.get(URL, listed),
      http.get('/api/journal-options/emotion_after', () => HttpResponse.json({ field: 'emotion_after', options: OPTIONS })),
    )
    renderWithProviders(<EmotionsSection />)
    expect(screen.getByText(t.before)).toBeInTheDocument()
    expect(screen.getByText(t.after)).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByLabelText(t.labelFor('тривога'))).toHaveLength(2))
  })

  it('renames by label and keeps the key', async () => {
    const sent: unknown[] = []
    mockApi(
      http.get(URL, listed),
      http.patch(`${URL}/calm`, async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json(OPTIONS[0])
      }),
    )
    const { user } = renderWithProviders(<OptionListEditor field="emotion_before" title="x" />)
    const input = await screen.findByLabelText(t.labelFor('спокій'))
    await user.clear(input)
    await user.type(input, 'рівновага')
    await user.tab()
    await waitFor(() => expect(sent).toEqual([{ label: 'рівновага' }]))
  })

  it('reorders with the arrows', async () => {
    const sent: unknown[] = []
    mockApi(
      http.get(URL, listed),
      http.put(`${URL}/order`, async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json({ field: 'emotion_before', options: OPTIONS })
      }),
    )
    const { user } = renderWithProviders(<OptionListEditor field="emotion_before" title="x" />)
    await user.click(await screen.findByRole('button', { name: t.moveDown('спокій') }))
    await waitFor(() => expect(sent).toEqual([{ values: ['anxiety', 'calm'] }]))
  })

  it('a used option can be hidden but its delete button is disabled', async () => {
    const sent: unknown[] = []
    mockApi(
      http.get(URL, listed),
      http.patch(`${URL}/calm`, async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json(OPTIONS[0])
      }),
    )
    const { user } = renderWithProviders(<OptionListEditor field="emotion_before" title="x" />)
    const row = (await screen.findByLabelText(t.labelFor('спокій'))).closest('li')
    expect(row).not.toBeNull()
    expect(within(row as HTMLElement).getByRole('button', { name: t.remove('спокій') })).toBeDisabled()
    expect(screen.getByRole('button', { name: t.remove('тривога') })).toBeEnabled()
    await user.click(within(row as HTMLElement).getByRole('button', { name: t.hide('спокій') }))
    await waitFor(() => expect(sent).toEqual([{ hidden: true }]))
  })

  it('adds an option with synonyms and shows a server error', async () => {
    const sent: unknown[] = []
    mockApi(
      http.get(URL, listed),
      http.post(URL, async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json({ error: { code: 'duplicate_label', message: 'exists' } }, { status: 409 })
      }),
    )
    const { user } = renderWithProviders(<OptionListEditor field="emotion_before" title="x" />)
    await user.type(await screen.findByLabelText(t.newLabel), 'азарт')
    await user.type(screen.getByLabelText(t.newSynonyms), 'азартно, excited')
    await user.click(screen.getByRole('button', { name: t.add }))
    await waitFor(() => expect(sent).toEqual([{ label: 'азарт', synonyms: ['азартно', 'excited'] }]))
    expect(await screen.findByRole('alert')).toHaveTextContent(t.saveError)
  })

  it('parses a comma list of synonyms', () => {
    expect(parseSynonyms(' a, ,b ,')).toEqual(['a', 'b'])
  })
})
