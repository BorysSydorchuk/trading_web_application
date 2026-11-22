import { uk } from '@/i18n/uk'
import type { RBucket } from '../types'

const c = uk.digests.charts

export interface RBin {
  key: string
  label: string
  count: number
  negative: boolean
}

/**
 * The snapshot's 0.5 R buckets folded into six clear bins by each bucket's lower edge. A bucket
 * [−1, −0.5) holds exactly −1 R, so that value belongs to «−1…0»; saved digests need no recompute.
 */
const BINS: readonly { key: string; below: number; label: string; negative: boolean }[] = [
  { key: 'below-1', below: -1, label: c.rBinBelow, negative: true },
  { key: '-1-0', below: 0, label: c.rBinMinusOne, negative: true },
  { key: '0-1', below: 1, label: c.rBinZero, negative: false },
  { key: '1-2', below: 2, label: c.rBinOne, negative: false },
  { key: '2-3', below: 3, label: c.rBinTwo, negative: false },
  { key: '3-up', below: Number.POSITIVE_INFINITY, label: c.rBinThree, negative: false },
]

export function foldRBuckets(buckets: readonly RBucket[]): RBin[] {
  const counts = BINS.map(() => 0)
  for (const bucket of buckets) {
    const lower = Number(bucket.lower)
    const index = BINS.findIndex((bin) => lower < bin.below)
    counts[index] = (counts[index] ?? 0) + bucket.count
  }
  return BINS.map((bin, i) => ({ key: bin.key, label: bin.label, negative: bin.negative, count: counts[i] ?? 0 }))
}
