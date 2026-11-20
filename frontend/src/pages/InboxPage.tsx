import { InboxList } from '@/features/inbox/InboxList'
import { NotificationPrompt } from '@/features/inbox/NotificationPrompt'
import { OpenUndescribed } from '@/features/inbox/OpenUndescribed'
import { uk } from '@/i18n/uk'

export function InboxPage() {
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-lg font-semibold tracking-tight">{uk.pages.inbox.title}</h1>
      <NotificationPrompt variant="inline" />
      <OpenUndescribed />
      <InboxList />
    </section>
  )
}
