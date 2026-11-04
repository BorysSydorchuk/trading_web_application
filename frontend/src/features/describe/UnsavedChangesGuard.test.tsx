import { useRef } from 'react'
import { screen } from '@testing-library/react'
import { Link } from 'react-router'
import { describe, expect, it } from 'vitest'
import { uk } from '@/i18n/uk'
import { renderWithProviders } from '@/test/render'
import { UnsavedChangesGuard } from './UnsavedChangesGuard'

const t = uk.describe.unsaved
const LINK_TEXT = 'other page'

function Page({ dirty, allowLeave = false }: { dirty: boolean; allowLeave?: boolean }) {
  const allowLeaveRef = useRef(allowLeave)
  return (
    <>
      <UnsavedChangesGuard dirty={dirty} allowLeaveRef={allowLeaveRef} />
      <Link to="/other">{LINK_TEXT}</Link>
    </>
  )
}

function setup(dirty: boolean, allowLeave = false) {
  return renderWithProviders(<Page dirty={dirty} allowLeave={allowLeave} />, {
    path: '/describe',
    routes: [{ path: '/other', element: <div data-testid="other-page" /> }],
  })
}

function beforeUnloadPrevented(): boolean {
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  return event.defaultPrevented
}

describe('UnsavedChangesGuard', () => {
  it('lets navigation through when nothing changed', async () => {
    const { user } = setup(false)
    await user.click(screen.getByRole('link', { name: LINK_TEXT }))

    expect(await screen.findByTestId('other-page')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('asks before leaving with unsaved changes: stay keeps the page, leave navigates', async () => {
    const { user, router } = setup(true)
    await user.click(screen.getByRole('link', { name: LINK_TEXT }))

    const dialog = await screen.findByRole('dialog', { name: t.title })
    expect(dialog).toHaveTextContent(t.description)
    await user.click(screen.getByRole('button', { name: t.stay }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/describe')

    await user.click(screen.getByRole('link', { name: LINK_TEXT }))
    await user.click(await screen.findByRole('button', { name: t.leave }))
    expect(await screen.findByTestId('other-page')).toBeInTheDocument()
  })

  it('does not ask after a successful save allowed leaving', async () => {
    const { user } = setup(true, true)
    await user.click(screen.getByRole('link', { name: LINK_TEXT }))

    expect(await screen.findByTestId('other-page')).toBeInTheDocument()
  })

  it('asks the browser to confirm closing the tab only while there are unsaved changes', () => {
    const { unmount } = setup(true)
    expect(beforeUnloadPrevented()).toBe(true)
    unmount()

    setup(false)
    expect(beforeUnloadPrevented()).toBe(false)
  })
})
