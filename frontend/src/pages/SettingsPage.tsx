import { AccountsSection } from '@/features/accounts/AccountsSection'
import { uk } from '@/i18n/uk'

export function SettingsPage() {
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-lg font-semibold tracking-tight">{uk.pages.settings.title}</h1>
      <AccountsSection />
    </div>
  )
}
