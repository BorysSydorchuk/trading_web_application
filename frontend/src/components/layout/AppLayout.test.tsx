import { act, render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { describe, expect, it } from 'vitest'
import { createTestQueryClient } from '@/test/render'
import { mockApi } from '@/test/server'
import { AppLayout } from './AppLayout'

function renderLayout() {
  mockApi(http.get('/api/*', () => HttpResponse.json({}, { status: 503 })))
  const router = createMemoryRouter(
    [{ element: <AppLayout />, children: [{ path: '*', element: null }] }],
    { initialEntries: ['/journal'] },
  )
  render(
    <QueryClientProvider client={createTestQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  const main = screen.getByRole('main')
  const scrollDown = () => {
    main.scrollTop = 500
  }
  return { router, main, scrollDown }
}

describe('AppLayout (M8-11)', () => {
  it('positions <main> so absolute content is clipped by its scroll area, not the document', () => {
    const { main } = renderLayout()
    expect(main).toHaveClass('relative', 'overflow-y-auto')
  })

  it('a new page starts at the top of the content area', async () => {
    const { router, main, scrollDown } = renderLayout()
    scrollDown()
    await act(() => router.navigate('/digests'))
    expect(main.scrollTop).toBe(0)
  })

  it('a replace navigation keeps the scroll position (editor stays mounted)', async () => {
    const { router, main, scrollDown } = renderLayout()
    await act(() => router.navigate('/bias/new'))
    scrollDown()
    await act(() => router.navigate('/bias/42', { replace: true }))
    expect(main.scrollTop).toBe(500)
  })
})
