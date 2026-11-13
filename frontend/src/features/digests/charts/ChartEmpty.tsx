import { uk } from '@/i18n/uk'

/** A chart without data: the title and a calm note. */
export function ChartEmpty({ title }: { title: string }) {
  return (
    <figure className="flex flex-col gap-1">
      <figcaption className="text-xs font-medium">{title}</figcaption>
      <p className="rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
        {uk.digests.charts.empty}
      </p>
    </figure>
  )
}
