/**
 * TradingView chart links (docs/api.md "Journal save" → chart_links). The URL regex, the
 * duplicate rule and the preview formula are the same as on the backend.
 */
import { uk } from '@/i18n/uk'

export const MAX_CHART_LINKS = 10
export const MAX_URL_LENGTH = 500
export const LINK_KINDS = ['before', 'after'] as const
export type LinkKind = (typeof LINK_KINDS)[number]

/** Path part of the contract regex; matched case-sensitively (the snapshot id is case-sensitive). */
const PATH_RE = /^\/(x\/[A-Za-z0-9]+\/?|chart(\/([A-Za-z0-9]+\/?)?)?)(\?[^#\s]*)?(#\S*)?$/
/** Scheme + host part; case-insensitive like the contract. */
const ORIGIN_RE = /^https:\/\/([a-z0-9-]+\.)?tradingview\.com$/i
const SPLIT_RE = /^([^/?#]*\/\/[^/?#]*)(.*)$/s
const SNAPSHOT_RE = /^https:\/\/([a-z0-9-]+\.)?tradingview\.com\/x\/([A-Za-z0-9]+)\/?(?:[?#]|$)/i

export interface LinkDraft {
  /** Client-side row id (React key, maps server errors back to the row). */
  rowId: string
  url: string
  kind: LinkKind
  /** From the server for saved links; null for new ones (computed from the URL instead). */
  previewUrl: string | null
}

let rowCounter = 0

export function newLinkRow(url = '', kind: LinkKind = 'before', previewUrl: string | null = null): LinkDraft {
  rowCounter += 1
  return { rowId: `link-${rowCounter}`, url, kind, previewUrl }
}

export function isValidChartUrl(url: string): boolean {
  if (url.length === 0 || url.length > MAX_URL_LENGTH) return false
  const match = SPLIT_RE.exec(url)
  if (!match) return false
  return ORIGIN_RE.test(match[1] ?? '') && PATH_RE.test(match[2] ?? '')
}

/**
 * Duplicate key (same as the backend): scheme + host lower-cased, path kept as is (snapshot ids
 * are case-sensitive), exactly one trailing slash, query and fragment ignored.
 */
export function chartUrlKey(url: string): string {
  const withoutQuery = url.split(/[?#]/, 1)[0] ?? ''
  const match = SPLIT_RE.exec(withoutQuery)
  const origin = (match?.[1] ?? '').toLowerCase()
  const path = (match?.[2] ?? withoutQuery).replace(/\/+$/, '')
  return `${origin}${path}/`
}

/** Snapshot thumbnail (same formula as the backend); null for /chart links. */
export function snapshotPreviewUrl(url: string): string | null {
  const id = SNAPSHOT_RE.exec(url)?.[2]
  if (!id) return null
  return `https://s3.tradingview.com/snapshots/${id.charAt(0).toLowerCase()}/${id}.png`
}

export function isLinkKind(value: string): value is LinkKind {
  return (LINK_KINDS as readonly string[]).includes(value)
}

/** Rows that will be sent: blank URL rows are ignored. */
export function filledLinks(links: readonly LinkDraft[]): LinkDraft[] {
  return links.filter((link) => link.url.trim() !== '')
}

/** Client errors per row id: invalid URL or a duplicate of an earlier row. */
export function linkErrors(links: readonly LinkDraft[]): Record<string, string> {
  const errors: Record<string, string> = {}
  const seen = new Set<string>()
  for (const link of filledLinks(links)) {
    const url = link.url.trim()
    if (!isValidChartUrl(url)) {
      errors[link.rowId] = uk.describe.links.invalid
      continue
    }
    const key = chartUrlKey(url)
    if (seen.has(key)) errors[link.rowId] = uk.describe.links.duplicate
    seen.add(key)
  }
  return errors
}

export function hasBeforeLink(links: readonly LinkDraft[]): boolean {
  return filledLinks(links).some((link) => link.kind === 'before')
}
