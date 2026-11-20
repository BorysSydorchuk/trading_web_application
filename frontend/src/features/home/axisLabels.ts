/**
 * Date / time labels under the «Головна» hero chart (M8-10b owner fix): labels come from the actual
 * span of the points and are spaced by their rendered width in pixels, so they never overlap and no
 * text repeats.
 */
import { uk } from '@/i18n/uk'
import { brusselsDayMonth, brusselsMonth } from './dates'

export type LabelAlign = 'start' | 'center' | 'end'

export interface AxisCandidate {
  /** Point index the label belongs to. */
  index: number
  text: string
}

export interface AxisLabel extends AxisCandidate {
  /** Which edge of the text sits on the point: the first point starts there, the last ends there. */
  align: LabelAlign
}

/** Spans shorter than this many days get DD.MM labels even for «3 міс» / «Рік» / «Усе». */
export const MONTH_LABELS_MIN_DAYS = 42
/** At most this many labels, however wide the chart is. */
export const AXIS_LABELS_MAX = 6
/** Minimum distance between two label anchors, px. */
export const AXIS_MIN_GAP_PX = 56
/** Minimum free space between two label boxes, px. */
export const AXIS_LABEL_PAD_PX = 8
/** Width estimate of one character of an 11 px label (a little wider than the real glyphs). */
const CHAR_PX = 7
const LABEL_EXTRA_PX = 4
const DAY_MS = 86_400_000

const t = uk.home.hero

/** Estimated rendered width of a label, px. */
export const labelWidthPx = (text: string) => text.length * CHAR_PX + LABEL_EXTRA_PX

/** Whole days from the first to the last instant (0 for fewer than two valid instants). */
export function spanDays(times: readonly string[]): number {
  const ms = times.map((iso) => new Date(iso).getTime()).filter(Number.isFinite)
  if (ms.length < 2) return 0
  return (Math.max(...ms) - Math.min(...ms)) / DAY_MS
}

/** One candidate per distinct text; the last point's text sits on the last point (right edge). */
function distinct(texts: readonly string[]): AxisCandidate[] {
  const last = texts.length - 1
  const byText = new Map<string, number>()
  texts.forEach((text, index) => {
    if (!text) return
    if (!byText.has(text) || index === last) byText.set(text, index)
  })
  return [...byText.entries()].map(([text, index]) => ({ index, text })).sort((a, b) => a.index - b.index)
}

/** «28.10» per point (or any per-point formatter, e.g. «14:42»), one candidate per distinct text. */
export function pointCandidates(times: readonly string[], label: (iso: string) => string = brusselsDayMonth): AxisCandidate[] {
  return distinct(times.map(label))
}

/** «вер», «жов» at month starts (the first point labels its own month); «січ 27» when the span crosses years. */
export function monthCandidates(times: readonly string[]): AxisCandidate[] {
  const months = times.map(brusselsMonth)
  const withYear = new Set(months.flatMap((m) => (m ? [m.year] : []))).size > 1
  const texts = months.map((m) => {
    if (!m) return ''
    const name = t.monthsShort[m.month - 1] ?? ''
    return withYear ? t.monthYear(name, String(m.year % 100).padStart(2, '0')) : name
  })
  // A month is labelled at its first point only (not on the last point like days).
  const seen = new Set<string>()
  return texts.flatMap((text, index) => {
    if (!text || seen.has(text)) return []
    seen.add(text)
    return [{ index, text }]
  })
}

/** Month names for long ranges whose actual span is at least 6 weeks; DD.MM otherwise. */
export function dateCandidates(times: readonly string[], longRange: boolean): AxisCandidate[] {
  return longRange && spanDays(times) >= MONTH_LABELS_MIN_DAYS ? monthCandidates(times) : pointCandidates(times)
}

interface Box {
  left: number
  right: number
  anchor: number
  align: LabelAlign
}

/** Where a label sits: the first point starts at its x, the last ends there, others are centred inside the plot. */
function boxOf(index: number, text: string, pointCount: number, plotWidthPx: number): Box {
  const anchor = pointCount <= 1 ? plotWidthPx / 2 : (index * plotWidthPx) / (pointCount - 1)
  const width = labelWidthPx(text)
  let align: LabelAlign = 'center'
  if (pointCount > 1 && index === 0) align = 'start'
  else if (pointCount > 1 && index === pointCount - 1) align = 'end'
  else if (anchor - width / 2 < 0) align = 'start'
  else if (anchor + width / 2 > plotWidthPx) align = 'end'
  const left = align === 'start' ? anchor : align === 'end' ? anchor - width : anchor - width / 2
  return { left, right: left + width, anchor, align }
}

const clash = (a: Box, b: Box, gapPx: number) =>
  Math.abs(a.anchor - b.anchor) < gapPx || (a.left < b.right + AXIS_LABEL_PAD_PX && b.left < a.right + AXIS_LABEL_PAD_PX)

/**
 * Keeps the candidates that fit: the first and last ones first, then the rest left to right, each
 * dropped when it would sit closer than the gap (at least 56 px, wider on a wide chart so at most
 * six labels show) or touch a kept label's box. Texts never repeat.
 */
export function spacedAxisLabels(candidates: readonly AxisCandidate[], pointCount: number, plotWidthPx: number): AxisLabel[] {
  if (candidates.length === 0 || pointCount <= 0 || plotWidthPx <= 0) return []
  const gapPx = Math.max(AXIS_MIN_GAP_PX, plotWidthPx / AXIS_LABELS_MAX)
  const first = candidates[0]
  const last = candidates[candidates.length - 1]
  const order = [first, last, ...candidates.slice(1, -1)].filter((c): c is AxisCandidate => c !== undefined)
  const kept: (AxisCandidate & Box)[] = []
  const texts = new Set<string>()
  for (const candidate of order) {
    if (texts.has(candidate.text)) continue
    const box = boxOf(candidate.index, candidate.text, pointCount, plotWidthPx)
    if (kept.some((other) => clash(box, other, gapPx))) continue
    kept.push({ ...candidate, ...box })
    texts.add(candidate.text)
  }
  return kept.sort((a, b) => a.index - b.index).map(({ index, text, align }) => ({ index, text, align }))
}

/** Hero x labels for points at `times` drawn over `plotWidthPx` pixels. */
export function heroXLabels(times: readonly string[], longRange: boolean, plotWidthPx: number): AxisLabel[] {
  return spacedAxisLabels(dateCandidates(times, longRange), times.length, plotWidthPx)
}
