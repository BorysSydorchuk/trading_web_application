/**
 * MSW server for component tests (started in setup.ts). Each test declares its API answers
 * with `mockApi(...)`; they are reset after every test. A request without a handler fails
 * the test (checked in setup.ts).
 */
import { http, HttpResponse, type RequestHandler } from 'msw'
import { setupServer } from 'msw/node'

/**
 * Initial handlers (kept by resetHandlers): M8-13 AI model list. Empty, so the model picker
 * stays hidden and requests carry no `model` unless a test mocks its own list.
 */
const DEFAULTS: RequestHandler[] = [
  http.get('/api/ai/models', () =>
    HttpResponse.json({
      models: [],
      defaults: { trade_extraction: 'claude-sonnet-5-5', bias_extraction: 'claude-sonnet-5-5', digest_summary: 'claude-opus-5-5' },
    }),
  ),
]

export const server = setupServer(...DEFAULTS)

/** Requests that reached no handler in the current test. */
export const unhandledRequests: string[] = []

/** Declare the API answers for the current test. */
export function mockApi(...handlers: RequestHandler[]): void {
  server.use(...handlers)
}
