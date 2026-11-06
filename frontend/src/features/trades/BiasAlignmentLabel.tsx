import { uk } from '@/i18n/uk'
import type { BiasAlignment } from './types'

/** A null alignment has not been computed yet; it does not mean that bias is missing. */
export function BiasAlignmentLabel({ value }: { value: BiasAlignment | null }) {
  return <span className="text-xs">{value === null ? uk.bias.alignment.pending : uk.bias.alignment[value]}</span>
}
