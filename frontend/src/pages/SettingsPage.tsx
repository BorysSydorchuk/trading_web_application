import { AccountsSection } from '@/features/accounts/AccountsSection'
import { AiModelsSection } from '@/features/ai/AiModelsSection'
import { AiUsageSection } from '@/features/ai/AiUsageSection'
import { DesktopSection } from '@/features/system/DesktopSection'
import { uk } from '@/i18n/uk'

export function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold tracking-tight">{uk.pages.settings.title}</h1>
      <AccountsSection />
      <AiUsageSection />
      <AiModelsSection />
      <DesktopSection />
    </div>
  )
}
