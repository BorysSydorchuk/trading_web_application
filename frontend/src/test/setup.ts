/** Setup for component tests (`*.test.tsx`, jsdom): jest-dom matchers, cleanup, MSW server. */
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, expect } from 'vitest'
import { server, unhandledRequests } from './server'

// jsdom does not implement scrolling (the Describe screen scrolls to the first missing field).
Element.prototype.scrollIntoView = () => undefined

function describeFrame(data: unknown, protocol: string): string {
  const request = typeof data === 'object' && data !== null && 'request' in data ? data.request : null
  return request instanceof Request ? `${request.method} ${request.url}` : protocol
}

beforeAll(() => {
  server.listen({
    // A request without a handler: print MSW's error, fail the request (never reach the real
    // network) and fail the test in afterEach, even if the app swallowed the network error.
    onUnhandledFrame: ({ frame, defaults }) => {
      defaults.error()
      unhandledRequests.push(describeFrame(frame.data, frame.protocol))
      throw new Error('No MSW handler for this request')
    },
  })
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  const unhandled = unhandledRequests.splice(0)
  expect(unhandled, 'requests without an MSW handler').toEqual([])
})

afterAll(() => server.close())
