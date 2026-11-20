import { uk } from '@/i18n/uk'

/** A chart without data: the title and a calm note. */
export function ChartEmpty({ title }: { title: string }) {
  return (
    <figure className="flex flex-col gap-2 rounded-card border border-line bg-card p-4">
      <figcaption className="font-display text-sm font-extrabold text-ink">{title}</figcaption>
      <p className="rounded-tile border border-dashed border-input px-3 py-4 text-center text-xs text-ink-muted">
        {uk.digests.charts.empty}
      </p>
    </figure>
  )
}
