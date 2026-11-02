import { Loader2 } from 'lucide-react'
import { uk } from '@/i18n/uk'

/** Shown while a lazily loaded page chunk is fetched on first load. */
export function PageLoading() {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-xs text-muted-foreground">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {uk.loadingPage}
    </div>
  )
}
