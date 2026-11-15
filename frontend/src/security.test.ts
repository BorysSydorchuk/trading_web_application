import { expect, it } from 'vitest'
import config from '../vite.config'

it('does not allow another website to frame the local UI (dev or preview)', () => {
  for (const server of [config.server, config.preview]) {
    expect(server?.host).toBe('127.0.0.1')
    expect(server?.headers?.['X-Frame-Options']).toBe('DENY')
    expect(server?.headers?.['Content-Security-Policy']).toBe("frame-ancestors 'none'")
  }
})
