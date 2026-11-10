import { CalculatorForm } from '@/features/calculator/CalculatorForm'
import { uk } from '@/i18n/uk'

/** /calculator: position-size calculator (PRD 6.8). */
export function CalculatorPage() {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight">{uk.pages.calculator.title}</h1>
        <p className="text-xs text-muted-foreground">{uk.pages.calculator.description}</p>
      </div>
      <CalculatorForm />
    </section>
  )
}
