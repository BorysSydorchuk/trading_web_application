import { describe, expect, it } from 'vitest'
import {
  AXIS_LABEL_PAD_PX,
  AXIS_MIN_GAP_PX,
  dateCandidates,
  heroXLabels,
  labelWidthPx,
  monthCandidates,
  pointCandidates,
  spacedAxisLabels,
  type AxisLabel,
} from './axisLabels'

/** One trade a day at 10:00 UTC from `start` ("YYYY-MM-DD") for `days` days. */
function daily(start: string, days: number): string[] {
  const first = new Date(`${start}T10:00:00Z`).getTime()
  return Array.from({ length: days }, (_, i) => new Date(first + i * 86_400_000).toISOString())
}

/** Label boxes in px, laid out like HeroChart (start / centre / end on the point's x). */
function boxes(labels: readonly AxisLabel[], count: number, width: number) {
  return labels.map(({ index, text, align }) => {
    const anchor = count <= 1 ? width / 2 : (index * width) / (count - 1)
    const w = labelWidthPx(text)
    const left = align === 'start' ? anchor : align === 'end' ? anchor - w : anchor - w / 2
    return { anchor, left, right: left + w }
  })
}

function expectSpaced(labels: readonly AxisLabel[], count: number, width: number) {
  const texts = labels.map((l) => l.text)
  expect(new Set(texts).size).toBe(texts.length)
  const b = boxes(labels, count, width)
  for (let i = 1; i < b.length; i++) {
    const prev = b[i - 1]
    const cur = b[i]
    if (!prev || !cur) continue
    expect(cur.anchor - prev.anchor).toBeGreaterThanOrEqual(AXIS_MIN_GAP_PX)
    expect(cur.left - prev.right).toBeGreaterThanOrEqual(AXIS_LABEL_PAD_PX)
  }
  for (const box of b) {
    expect(box.left).toBeGreaterThanOrEqual(0)
    expect(box.right).toBeLessThanOrEqual(width)
  }
}

describe('hero x labels (actual span, pixel spacing)', () => {
  // The owner's case: trades from 28.10 to 20.11, the span start moved to the first trade.
  const short = daily('2026-10-28', 24)

  it('a short history in a long range («Рік», «Усе») gets DD.MM labels, not month names', () => {
    const labels = heroXLabels(short, true, 800)
    expect(labels[0]).toEqual({ index: 0, text: '28.10', align: 'start' })
    expect(labels.at(-1)).toEqual({ index: 23, text: '20.11', align: 'end' })
    expect(labels.every((l) => /^\d{2}\.\d{2}$/.test(l.text))).toBe(true)
    expectSpaced(labels, short.length, 800)
  })

  it('never repeats a text and keeps the minimum gap on narrow and wide charts', () => {
    // Several trades a day: the same DD.MM on many points.
    const busy = short.flatMap((iso) => [iso, iso.replace('T10', 'T13'), iso.replace('T10', 'T15')])
    for (const width of [200, 380, 560, 640, 900, 1200]) {
      const labels = heroXLabels(busy, false, width)
      expect(labels.length).toBeGreaterThan(0)
      expectSpaced(labels, busy.length, width)
      expect(labels.length).toBeLessThanOrEqual(Math.floor(width / AXIS_MIN_GAP_PX) + 1)
    }
  })

  it('a span of 6 weeks or more in a long range gets month names; a short range keeps DD.MM', () => {
    const year = daily('2026-01-05', 300)
    const labels = heroXLabels(year, true, 800)
    expect(labels.map((l) => l.text)).toEqual(['січ', 'бер', 'тра', 'лип', 'жов'])
    expectSpaced(labels, year.length, 800)
    expect(dateCandidates(daily('2026-09-01', 43), true)[1]?.text).toBe('жов')
    expect(dateCandidates(daily('2026-09-01', 42), true)[1]?.text).toBe('02.09')
    expect(dateCandidates(year, false)[0]?.text).toBe('05.01')
  })

  it('month names carry the year when the span crosses years', () => {
    expect(monthCandidates(daily('2026-11-20', 60)).map((c) => c.text)).toEqual(['лис 26', 'гру 26', 'січ 27'])
  })

  it('the last DD.MM sits on the last point; one point is centred; nothing for no points', () => {
    expect(pointCandidates(['2026-11-19T08:00:00Z', '2026-11-19T12:00:00Z'])).toEqual([{ index: 1, text: '19.11' }])
    expect(spacedAxisLabels([{ index: 0, text: '19.11' }], 1, 600)).toEqual([{ index: 0, text: '19.11', align: 'center' }])
    expect(heroXLabels([], true, 600)).toEqual([])
  })
})
