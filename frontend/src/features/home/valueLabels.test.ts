import { describe, expect, it } from 'vitest'
import { spacedValueLabels, VALUE_LABEL_PAD_PX, valueLabelBox, type ValueLabelInput } from './valueLabels'

const label = (index: number, kind: ValueLabelInput['kind'], x: number, y: number, text = '+1 111'): ValueLabelInput => ({ index, text, kind, x, y })

describe('spacedValueLabels (hero value labels, measured boxes)', () => {
  it('drops a point label that would touch the last pill (the owner case «+1 111» under «+1 240»)', () => {
    expect(spacedValueLabels([label(30, 'point', 565, 50), label(33, 'last', 600, 40, '+1 240')])).toEqual([33])
  })

  it('the minimum wins over a point label, both stay when apart', () => {
    expect(spacedValueLabels([label(1, 'point', 100, 100), label(2, 'min', 110, 70, '−45')])).toEqual([2])
    expect(spacedValueLabels([label(1, 'point', 100, 100), label(5, 'min', 300, 100, '−45'), label(9, 'last', 600, 40)])).toEqual([1, 5, 9])
  })

  it('labels at the same height keep 8 px between boxes; at different heights they may share x', () => {
    const a = valueLabelBox(label(1, 'point', 100, 100))
    const width = a.right - a.left
    const touching = 100 + width + VALUE_LABEL_PAD_PX - 1
    expect(spacedValueLabels([label(1, 'point', 100, 100), label(2, 'point', touching, 100)])).toEqual([1])
    expect(spacedValueLabels([label(1, 'point', 100, 100), label(2, 'point', touching + 2, 100)])).toEqual([1, 2])
    expect(spacedValueLabels([label(1, 'point', 100, 100), label(2, 'point', 100, 160)])).toEqual([1, 2])
  })

  it('kept labels never overlap pairwise', () => {
    const many = Array.from({ length: 40 }, (_, i) => label(i, i === 39 ? 'last' : 'point', i * 15, 200 - i * 4))
    const kept = spacedValueLabels(many).map((i) => valueLabelBox(many[i] as ValueLabelInput))
    for (const [n, a] of kept.entries()) {
      for (const b of kept.slice(n + 1)) {
        const vertical = a.top < b.bottom && b.top < a.bottom
        expect(vertical && a.left < b.right + VALUE_LABEL_PAD_PX && b.left < a.right + VALUE_LABEL_PAD_PX).toBe(false)
      }
    }
  })
})
