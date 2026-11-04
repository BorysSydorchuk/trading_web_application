/**
 * MSW server for component tests (started in setup.ts). Each test declares its API answers
 * with `mockApi(...)`; they are reset after every test. A request without a handler fails
 * the test (checked in setup.ts).
 */
import type { RequestHandler } from 'msw'
import { setupServer } from 'msw/node'

export const server = setupServer()

/** Requests that reached no handler in the current test. */
export const unhandledRequests: string[] = []

/** Declare the API answers for the current test. */
export function mockApi(...handlers: RequestHandler[]): void {
  server.use(...handlers)
}
