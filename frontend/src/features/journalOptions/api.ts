import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiRequest } from '@/api/client'
import { journalFieldKeys } from '@/features/trades/api'

/** docs/api.md `GET /api/journal-options/{field}`; `value` is the stable key stored on trades. */
export interface EditableOption {
  value: string
  label: string
  hidden: boolean
  synonyms: string[]
  used_count: number
}

interface OptionList {
  field: string
  options: EditableOption[]
}

export interface OptionChange {
  label?: string
  hidden?: boolean
  synonyms?: string[]
}

export type OptionAction =
  | { kind: 'add'; label: string; synonyms: string[] }
  | { kind: 'update'; value: string; change: OptionChange }
  | { kind: 'order'; values: string[] }
  | { kind: 'delete'; value: string }

/** The comma-separated synonyms input as a clean list. */
export function parseSynonyms(text: string): string[] {
  return text
    .split(',')
    .map((word) => word.trim())
    .filter((word) => word !== '')
}

const optionKeys ={ list: (field: string) => ['journal-options', field] as const }

function send(field: string, action: OptionAction): Promise<unknown> {
  const base = `/journal-options/${field}`
  switch (action.kind) {
    case 'add':
      return apiRequest(base, { method: 'POST', body: { label: action.label, synonyms: action.synonyms } })
    case 'update':
      return apiRequest(`${base}/${action.value}`, { method: 'PATCH', body: action.change })
    case 'order':
      return apiRequest(`${base}/order`, { method: 'PUT', body: { values: action.values } })
    case 'delete':
      return apiRequest(`${base}/${action.value}`, { method: 'DELETE' })
  }
}

export function useEditableOptions(field: string) {
  return useQuery({
    queryKey: optionKeys.list(field),
    queryFn: ({ signal }) => apiGet<OptionList>(`/journal-options/${field}`, { signal }),
  })
}

/** Every change refreshes this list and the field definitions the form and filters read. */
export function useChangeOptions(field: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (action: OptionAction) => send(field, action),
    // One list saves one change at a time, in the order the owner made them.
    scope: { id: `journal-options:${field}` },
    meta: { silentError: true },
    onSettled: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: optionKeys.list(field) }),
        queryClient.invalidateQueries({ queryKey: journalFieldKeys.all }),
      ]),
  })
}
