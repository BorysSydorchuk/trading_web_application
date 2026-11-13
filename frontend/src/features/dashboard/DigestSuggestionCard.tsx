import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { useDigestSuggestion } from './api'
import { digestPath, formatMonth, formatWeekRange } from './format'

const s = uk.dashboard.suggestion

/** «Час переглянути тиждень 9–15 лист.»: the latest due period without a review (server decides). */
export function DigestSuggestionCard() {
  const { data, isError } = useDigestSuggestion()
  if (isError && !data) return <p className="text-xs text-muted-foreground">{s.loadError}</p>
  if (!data) return null
  const items = [
    data.weekly && { kind: 'weekly' as const, start: data.weekly.period_start, text: s.weekly(formatWeekRange(data.weekly.period_start)) },
    data.monthly && { kind: 'monthly' as const, start: data.monthly.period_start, text: s.monthly(formatMonth(data.monthly.period_start)) },
  ].filter((item) => item !== null)
  if (items.length === 0) return null
  return (
    <>
      {items.map((item) => (
        <article
          key={item.kind}
          aria-label={item.text}
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-primary/40 px-4 py-3"
        >
          <p className="text-sm font-medium">{item.text}</p>
          <Button asChild size="sm" variant="outline">
            <Link to={digestPath(item.kind, item.start)}>{s.open}</Link>
          </Button>
        </article>
      ))}
    </>
  )
}
