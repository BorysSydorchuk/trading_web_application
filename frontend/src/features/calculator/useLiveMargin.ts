/**
 * Live MT5 margin after a successful calculate (docs/api.md "Margin integration design"):
 * POST /margin-requests with the same body, then GET every second until done/failed/expired.
 * A new job (new calculate or changed input) or unmount cancels the previous one, so a
 * superseded result is never shown.
 */
import { useEffect, useState } from 'react'
import { createMarginRequest, getMarginRequest } from './api'
import type { CalculateInput, MarginRequest } from './types'

export const MARGIN_POLL_MS = 1_000
/** The server expires a pending request after 60 s, but only a running worker does that. */
export const MARGIN_MAX_POLLS = 75

export interface MarginJob {
  /** Form version the job belongs to. */
  version: number
  input: CalculateInput
}

export type LiveMargin =
  | { state: 'pending' }
  | { state: 'done'; amount: string; currency: string; at: string | null }
  /** Live margin did not come (failed, expired, request error, gave up waiting). */
  | { state: 'failed'; reason: 'failed' | 'expired' | 'error'; code: string | null }

const PENDING: LiveMargin = { state: 'pending' }

function settled(item: MarginRequest): LiveMargin | null {
  if (item.status === 'done' && item.amount !== null) {
    return { state: 'done', amount: item.amount, currency: item.currency, at: item.finished_at }
  }
  if (item.status === 'done' || item.status === 'failed') return { state: 'failed', reason: 'failed', code: item.error_code }
  if (item.status === 'expired') return { state: 'failed', reason: 'expired', code: item.error_code }
  return null
}

const ERROR: LiveMargin = { state: 'failed', reason: 'error', code: null }

interface Outcome {
  version: number
  margin: LiveMargin
}

export function useLiveMargin(job: MarginJob | null): LiveMargin | null {
  const [outcome, setOutcome] = useState<Outcome | null>(null)

  useEffect(() => {
    if (!job) return
    const controller = new AbortController()
    let active = true
    let timer: ReturnType<typeof setInterval> | undefined
    let inFlight = false
    let polls = 0

    const finish = (margin: LiveMargin) => {
      if (!active) return
      active = false
      clearInterval(timer)
      setOutcome({ version: job.version, margin })
    }
    const handle = (item: MarginRequest) => {
      const result = settled(item)
      if (result) finish(result)
      else if (polls >= MARGIN_MAX_POLLS) finish({ state: 'failed', reason: 'expired', code: null })
    }
    const poll = async (id: number) => {
      if (inFlight || !active) return
      inFlight = true
      polls += 1
      try {
        const item = await getMarginRequest(id, controller.signal)
        if (active) handle(item)
      } catch {
        finish(ERROR)
      } finally {
        inFlight = false
      }
    }

    createMarginRequest(job.input, controller.signal)
      .then((item) => {
        if (!active) return
        const result = settled(item)
        if (result) finish(result)
        else timer = setInterval(() => void poll(item.id), MARGIN_POLL_MS)
      })
      .catch(() => finish(ERROR))

    return () => {
      active = false
      clearInterval(timer)
      controller.abort()
    }
  }, [job])

  if (!job) return null
  return outcome?.version === job.version ? outcome.margin : PENDING
}
