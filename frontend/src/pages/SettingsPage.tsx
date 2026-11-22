import { AccountsSection } from '@/features/accounts/AccountsSection'
import { AiModelsSection } from '@/features/ai/AiModelsSection'
import { AiUsageSection } from '@/features/ai/AiUsageSection'
import { EmotionsSection } from '@/features/journalOptions/EmotionsSection'
import { DesktopSection } from '@/features/system/DesktopSection'
import { uk } from '@/i18n/uk'

export function SettingsPage() {
  return (
    <div className="flex flex-col gap-8">
      <h1 className="type-page-title m-0 text-ink">{uk.pages.settings.title}</h1>
      <AccountsSection />
      <EmotionsSection />
      <AiUsageSection />
      <AiModelsSection />
      <DesktopSection />
    </div>
  )
}
