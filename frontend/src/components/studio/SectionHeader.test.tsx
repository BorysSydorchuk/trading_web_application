import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Pill } from './Pill'
import { SectionHeader } from './SectionHeader'

const ACTION = 'дія'
const PNL = '+68'

describe('SectionHeader', () => {
  it('renders an h2 section title with badges and actions', () => {
    render(
      <SectionHeader id="open" title="Відкриті позиції" actions={<button type="button">{ACTION}</button>}>
        <Pill tone="profit">{PNL}</Pill>
      </SectionHeader>,
    )
    const heading = screen.getByRole('heading', { level: 2, name: 'Відкриті позиції' })
    expect(heading).toHaveAttribute('id', 'open')
    expect(heading).toHaveClass('type-section-title')
    expect(screen.getByText(PNL)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: ACTION })).toBeInTheDocument()
  })

  it('supports level 3', () => {
    render(<SectionHeader level={3} title="Ліміти" />)
    expect(screen.getByRole('heading', { level: 3, name: 'Ліміти' })).toBeInTheDocument()
  })
})
