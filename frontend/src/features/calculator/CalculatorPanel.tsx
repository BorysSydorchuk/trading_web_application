import { Link } from 'react-router'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { CalculatorForm } from './CalculatorForm'

const t = uk.calculator.home

/** Compact calculator on the dashboard (PRD 6.10 quick link) with a link to the full page. */
export function CalculatorPanel() {
  return (
    <section aria-label={t.title} className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{t.title}</h2>
        <Button asChild size="sm" variant="outline"><Link to="/calculator">{t.openFull}</Link></Button>
      </div>
      <CalculatorForm compact />
    </section>
  )
}
