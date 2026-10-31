import {
  BookOpen,
  Calculator,
  Compass,
  FileText,
  Inbox,
  LayoutDashboard,
  Settings,
  type LucideIcon,
} from 'lucide-react'
import { uk } from '@/i18n/uk'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
}

/** Sidebar order is fixed by ROADMAP M0. */
export const navItems: readonly NavItem[] = [
  { to: '/', label: uk.nav.home, icon: LayoutDashboard },
  { to: '/inbox', label: uk.nav.inbox, icon: Inbox },
  { to: '/journal', label: uk.nav.journal, icon: BookOpen },
  { to: '/bias', label: uk.nav.bias, icon: Compass },
  { to: '/digests', label: uk.nav.digests, icon: FileText },
  { to: '/calculator', label: uk.nav.calculator, icon: Calculator },
  { to: '/settings', label: uk.nav.settings, icon: Settings },
]
