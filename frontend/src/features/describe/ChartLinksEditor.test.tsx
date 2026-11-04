import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { ChartLinksEditor } from './ChartLinksEditor'
import { linkErrors, type LinkDraft } from './chartLinks'
import { linksField } from './formModel'
import { FIXTURE_FIELDS } from './journalFields.fixture'

const l = uk.describe.links
const SNAPSHOT = 'https://www.tradingview.com/x/AbCd1234/'
const CHART = 'https://www.tradingview.com/chart/Xyz9/'

/** Same wiring as DescribeEditor: the parent owns the rows and passes the client errors back. */
function Harness() {
  const [links, setLinks] = useState<LinkDraft[]>([])
  return (
    <ChartLinksEditor
      field={linksField(FIXTURE_FIELDS)}
      links={links}
      errors={linkErrors(links)}
      missing={false}
      onChange={setLinks}
    />
  )
}

function setup() {
  const user = userEvent.setup()
  render(<Harness />)
  return user
}

describe('ChartLinksEditor', () => {
  it('adds a valid snapshot link with a preview and no error', async () => {
    const user = setup()
    expect(screen.getByText(l.empty)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: l.add }))
    await user.type(screen.getByRole('textbox', { name: l.urlLabel(1) }), SNAPSHOT)

    expect(screen.queryByText(l.empty)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: new RegExp(l.open) })).toHaveAttribute('href', SNAPSHOT)
    expect(screen.getByRole('img', { name: l.previewAlt })).toHaveAttribute(
      'src',
      'https://s3.tradingview.com/snapshots/a/AbCd1234.png',
    )
    expect(screen.getByRole('combobox', { name: l.kindLabel(1) })).toHaveValue('before')
  })

  it('shows an error for a link that is not TradingView', async () => {
    const user = setup()
    await user.click(screen.getByRole('button', { name: l.add }))
    const input = screen.getByRole('textbox', { name: l.urlLabel(1) })
    await user.type(input, 'https://example.com/x/AbCd1234/')

    expect(screen.getByRole('alert')).toHaveTextContent(l.invalid)
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByRole('link', { name: new RegExp(l.open) })).not.toBeInTheDocument()
  })

  it('marks a duplicate of an earlier row (query string ignored)', async () => {
    const user = setup()
    await user.click(screen.getByRole('button', { name: l.add }))
    await user.type(screen.getByRole('textbox', { name: l.urlLabel(1) }), SNAPSHOT)
    await user.click(screen.getByRole('button', { name: l.add }))
    await user.type(screen.getByRole('textbox', { name: l.urlLabel(2) }), `${SNAPSHOT}?theme=dark`)

    const alerts = screen.getAllByRole('alert')
    expect(alerts).toHaveLength(1)
    expect(alerts[0]).toHaveTextContent(l.duplicate)
    expect(screen.getByRole('textbox', { name: l.urlLabel(2) })).toHaveAttribute('aria-invalid', 'true')
    // A "before" link exists, so the next row defaults to "after".
    expect(screen.getByRole('combobox', { name: l.kindLabel(2) })).toHaveValue('after')
  })

  it('splits several pasted URLs into rows and removes a row', async () => {
    const user = setup()
    await user.click(screen.getByRole('button', { name: l.add }))
    await user.click(screen.getByRole('textbox', { name: l.urlLabel(1) }))
    await user.paste(`${SNAPSHOT}\n${CHART}`)

    expect(screen.getByRole('textbox', { name: l.urlLabel(1) })).toHaveValue(SNAPSHOT)
    expect(screen.getByRole('textbox', { name: l.urlLabel(2) })).toHaveValue(CHART)

    const [removeFirst] = screen.getAllByRole('button', { name: l.remove })
    if (!removeFirst) throw new Error('no remove button')
    await user.click(removeFirst)
    expect(screen.getByRole('textbox', { name: l.urlLabel(1) })).toHaveValue(CHART)
    expect(screen.queryByRole('textbox', { name: l.urlLabel(2) })).not.toBeInTheDocument()
  })
})
