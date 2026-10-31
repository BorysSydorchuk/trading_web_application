import { Link } from 'react-router'
import { PagePlaceholder } from '@/components/PagePlaceholder'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'

export function NotFoundPage() {
  return (
    <PagePlaceholder title={uk.pages.notFound.title} description={uk.pages.notFound.description}>
      <Button asChild size="sm" variant="outline">
        <Link to="/">{uk.pages.notFound.backHome}</Link>
      </Button>
    </PagePlaceholder>
  )
}
