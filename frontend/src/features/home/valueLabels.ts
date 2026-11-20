/**
 * Value labels over the «Головна» hero chart (M8-10b owner fix): boxes are estimated in pixels at the
 * rendered size and a lower-priority label is dropped when it would touch a kept one
 * (priority: last pill > minimum > other points).
 */

export type ValueLabelKind = 'last' | 'min' | 'point'

export interface ValueLabelInput {
  index: number
  text: string
  kind: ValueLabelKind
  /** Point position in px inside the chart box. */
  x: number
  y: number
}

export interface PxBox {
  left: number
  right: number
  top: number
  bottom: number
}

/** Horizontal free space required between two value labels that overlap vertically, px. */
export const VALUE_LABEL_PAD_PX = 8
/** Gap between the point and its label (CSS: 10px above, or below for the minimum). */
const OFFSET_PX = 10
/** The last pill is shifted 10px left of its point (CSS ml-[-10px]). */
const PILL_SHIFT_PX = 10

// Estimates a bit above the rendered sizes (13 px semibold pill with px-2 and border; 11 px with px-1).
const SIZE: Record<ValueLabelKind, { char: number; extra: number; height: number }> = {
  last: { char: 8.5, extra: 20, height: 26 },
  min: { char: 7, extra: 10, height: 18 },
  point: { char: 7, extra: 10, height: 18 },
}

const RANK: Record<ValueLabelKind, number> = { last: 0, min: 1, point: 2 }

/** Estimated box of a value label at its CSS position (last: right-aligned; min: below; others: above, centred). */
export function valueLabelBox({ text, kind, x, y }: ValueLabelInput): PxBox {
  const size = SIZE[kind]
  const width = text.length * size.char + size.extra
  const right = kind === 'last' ? x - PILL_SHIFT_PX : x + width / 2
  const top = kind === 'min' ? y + OFFSET_PX : y - OFFSET_PX - size.height
  return { left: right - width, right, top, bottom: top + size.height }
}

const collide = (a: PxBox, b: PxBox) =>
  a.left < b.right + VALUE_LABEL_PAD_PX && b.left < a.right + VALUE_LABEL_PAD_PX && a.top < b.bottom && b.top < a.bottom

/** Indices of the labels that stay: by priority, then left to right; a label touching a kept one is dropped. */
export function spacedValueLabels(labels: readonly ValueLabelInput[]): number[] {
  const order = [...labels].sort((a, b) => RANK[a.kind] - RANK[b.kind] || a.index - b.index)
  const kept: PxBox[] = []
  const indices: number[] = []
  for (const label of order) {
    const box = valueLabelBox(label)
    if (kept.some((other) => collide(box, other))) continue
    kept.push(box)
    indices.push(label.index)
  }
  return indices.sort((a, b) => a - b)
}
