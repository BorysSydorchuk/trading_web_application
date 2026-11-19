import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { mockApi } from '@/test/server'
import { AiModelsSection } from './AiModelsSection'
import { ModelPicker } from './ModelPicker'
import { useOneOffModel, type AiModels } from './models'

const t = uk.aiModels
const MODELS: AiModels = {
  models: [
    { id: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', approx_usd: { trade_extraction: '0.01', bias_extraction: '0.014', digest_summary: '0.023' } },
    { id: 'claude-opus-5-5', label: 'Claude Opus 5.5', approx_usd: { trade_extraction: '0.021', bias_extraction: '0.028', digest_summary: '0.046' } },
  ],
  defaults: { trade_extraction: 'claude-sonnet-5-5', bias_extraction: 'claude-sonnet-5-5', digest_summary: 'claude-opus-5-5' },
}

function Picker({ onModel }: { onModel: (m: string | undefined) => void }) {
  const pick = useOneOffModel('digest_summary')
  onModel(pick.model)
  return <ModelPicker {...pick} />
}

describe('M8-13 model choice', () => {
  it('Settings saves the default per call type and shows the approximate cost', async () => {
    const sent: unknown[] = []
    mockApi(
      http.get('/api/ai/models', () => HttpResponse.json(MODELS)),
      http.put('/api/ai/models/defaults', async ({ request }) => {
        sent.push(await request.json())
        return HttpResponse.json({ ...MODELS, defaults: { ...MODELS.defaults, trade_extraction: 'claude-opus-5-5' } })
      }),
    )
    const { user } = renderWithProviders(<AiModelsSection />)

    const select = await screen.findByLabelText(t.callTypes.trade_extraction)
    expect(select).toHaveValue('claude-sonnet-5-5')
    expect(screen.getAllByRole('option', { name: t.option('Claude Opus 5.5', '0.021') })).toHaveLength(1)

    await user.selectOptions(select, 'claude-opus-5-5')

    expect(sent).toEqual([{ trade_extraction: 'claude-opus-5-5' }])
    expect(await screen.findByLabelText(t.callTypes.trade_extraction)).toHaveValue('claude-opus-5-5')
  })

  it('the one-off picker starts at the default and can be changed for one call', async () => {
    mockApi(http.get('/api/ai/models', () => HttpResponse.json(MODELS)))
    const seen: (string | undefined)[] = []
    const { user } = renderWithProviders(<Picker onModel={(m) => seen.push(m)} />)

    const picker = await screen.findByRole('combobox', { name: t.pickerLabel })
    expect(picker).toHaveValue('claude-opus-5-5')
    expect(seen.at(-1)).toBeUndefined() // showing the default, sending none
    await user.selectOptions(picker, 'claude-sonnet-5-5')
    expect(seen.at(-1)).toBe('claude-sonnet-5-5')
  })

  it('sends no model until the owner picks one, also when the default is an .env id not listed', async () => {
    const envDefaults = { ...MODELS, defaults: { ...MODELS.defaults, digest_summary: 'claude-old-4' } }
    mockApi(http.get('/api/ai/models', () => HttpResponse.json(envDefaults)))
    const seen: (string | undefined)[] = []
    const { user } = renderWithProviders(<Picker onModel={(m) => seen.push(m)} />)

    const picker = await screen.findByRole('combobox', { name: t.pickerLabel })
    expect(picker).toHaveValue('claude-old-4')
    expect(screen.getByRole('option', { name: t.envOption('claude-old-4') })).toBeInTheDocument()
    expect(seen.at(-1)).toBeUndefined() // the server resolves its own default

    await user.selectOptions(picker, 'claude-opus-5-5')
    expect(seen.at(-1)).toBe('claude-opus-5-5')
  })

  it('shows a readable error for a model the AI service does not know', () => {
    expect(uk.errors.ai_error_kinds.model_not_found).toContain('моделі')
  })
})
