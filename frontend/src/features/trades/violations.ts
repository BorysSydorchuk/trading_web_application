import { useMemo } from 'react'
import { uk } from '@/i18n/uk'
import { useJournalFields } from './api'

/**
 * Rule key → Ukrainian label. Prefers the `rule_violations` options from
 * /api/journal-fields (config/journal_fields.yaml), falls back to uk.ts, then to the key.
 */
export function useViolationLabel(): (ruleKey: string) => string {
  const { data } = useJournalFields()
  return useMemo(() => {
    const fromConfig = new Map<string, string>()
    const field = data?.fields.find((f) => f.key === 'rule_violations')
    for (const option of field?.options ?? []) fromConfig.set(option.value, option.label)
    const fallback: Record<string, string> = uk.trades.rules
    return (ruleKey: string) =>
      fromConfig.get(ruleKey) ?? (Object.hasOwn(fallback, ruleKey) ? fallback[ruleKey] : undefined) ?? ruleKey
  }, [data])
}
