/**
 * Fetch wrapper for the backend API (docs/api.md).
 * - Base URL `/api` (proxied by Vite to 127.0.0.1:8000).
 * - Non-2xx responses carry `{ error: { code, message, details } }` -> thrown as ApiError.
 * - Network failures -> ApiError with code `network_error`; client-side timeout -> code `timeout`.
 * - Decimal values arrive as JSON strings and are passed through untouched.
 */

export const API_BASE = '/api'
const DEFAULT_TIMEOUT_MS = 10_000

export type ApiErrorDetails = Record<string, unknown> | null

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: ApiErrorDetails

  constructor(code: string, message: string, status: number, details: ApiErrorDetails = null) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.details = details
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

interface ErrorEnvelope {
  error: { code: string; message: string; details?: ApiErrorDetails }
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const inner = (value as { error: unknown }).error
  return (
    typeof inner === 'object' &&
    inner !== null &&
    typeof (inner as { code?: unknown }).code === 'string' &&
    typeof (inner as { message?: unknown }).message === 'string'
  )
}

/**
 * A non-2xx response without the contract envelope did not come from our API
 * (e.g. the Vite proxy answering 500/502 because the backend is down).
 */
function fallbackCode(status: number): string {
  if (status === 404) return 'not_found'
  if (status === 422) return 'validation_error'
  if (status >= 500) return 'network_error'
  return 'unknown'
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text()
  if (text === '') return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return undefined
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** Sent as JSON. */
  body?: unknown
  /** Sent as is (e.g. an audio upload), `Content-Type` = the blob's type. Wins over `body`. */
  rawBody?: Blob
  /** Arrays become repeated parameters (`status=a&status=b`). */
  query?: Record<
    string,
    string | number | boolean | null | undefined | readonly (string | number)[]
  >
  signal?: AbortSignal
  timeoutMs?: number
}

function buildUrl(path: string, query: RequestOptions['query']): string {
  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (Array.isArray(value)) {
      for (const item of value as readonly (string | number)[]) params.append(key, String(item))
    } else if (value !== undefined && value !== null && value !== '') {
      params.set(key, String(value))
    }
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

function buildBody({ body, rawBody }: RequestOptions): { headers: Record<string, string>; payload?: BodyInit } {
  if (rawBody !== undefined) {
    return { headers: { 'Content-Type': rawBody.type || 'application/octet-stream' }, payload: rawBody }
  }
  if (body !== undefined) return { headers: { 'Content-Type': 'application/json' }, payload: JSON.stringify(body) }
  return { headers: {} }
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = options
  const timeoutSignal = AbortSignal.timeout(timeoutMs)
  const combined = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal
  const { headers, payload: requestBody } = buildBody(options)

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: { Accept: 'application/json', ...headers },
      body: requestBody,
      signal: combined,
    })
  } catch (cause) {
    // Caller cancelled (e.g. TanStack Query cancellation): let the abort propagate as is.
    if (signal?.aborted) throw cause
    if (timeoutSignal.aborted) throw new ApiError('timeout', `No response within ${timeoutMs} ms`, 0)
    const message = cause instanceof Error ? cause.message : 'Network request failed'
    throw new ApiError('network_error', message, 0)
  }

  if (response.status === 204) return undefined as T

  const payload = await readJson(response)

  if (!response.ok) {
    if (isErrorEnvelope(payload)) {
      const { code, message, details } = payload.error
      throw new ApiError(code, message, response.status, details ?? null)
    }
    throw new ApiError(
      fallbackCode(response.status),
      `HTTP ${response.status} without error envelope`,
      response.status,
    )
  }

  if (payload === undefined) {
    throw new ApiError('internal_error', 'Response is not valid JSON', response.status)
  }
  return payload as T
}

export function apiGet<T>(path: string, options: Omit<RequestOptions, 'method' | 'body' | 'rawBody'> = {}) {
  return apiRequest<T>(path, { ...options, method: 'GET' })
}
