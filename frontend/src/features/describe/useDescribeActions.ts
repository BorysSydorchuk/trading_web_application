/** "Заповнити з тексту" and the two save buttons of the Describe screen. */
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { uk } from '@/i18n/uk'
import { useExtract, useSaveJournal } from './api'
import { fieldDomId } from './formModel'
import type { DescribeForm } from './useDescribeForm'

const t = uk.describe
const AFTER_SAVE_PATH = '/inbox'

function focusField(key: string | undefined) {
  if (!key) return
  const element = document.getElementById(fieldDomId(key))
  element?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  const focusable = element?.matches('input, select, textarea, button')
    ? element
    : element?.querySelector<HTMLElement>('input:not([disabled]), select, textarea, button')
  focusable?.focus({ preventScroll: true })
}

export function useDescribeActions(tradeId: number, form: DescribeForm) {
  const save = useSaveJournal(tradeId)
  const extract = useExtract(tradeId)
  const navigate = useNavigate()
  /** Set right before leaving after a successful save, so the unsaved-changes guard lets it through. */
  const allowLeaveRef = useRef(false)
  const [extractStartedAt, setExtractStartedAt] = useState<number | null>(null)

  function runExtract() {
    const text = form.rawText.trim()
    if (text === '') return
    setExtractStartedAt(Date.now())
    extract.mutate(text, {
      onSuccess: (result) => form.applyExtraction(result),
      onSettled: () => setExtractStartedAt(null),
    })
  }

  function submit(complete: boolean) {
    form.setShowMissing(true)
    if (form.hasClientErrors) {
      toast.error(t.save.fixErrors, { id: 'describe-client-errors' })
      return
    }
    if (complete && form.localMissing.length > 0) {
      toast.error(uk.errors.journal_incomplete, { id: 'api-error:journal_incomplete' })
      focusField(form.localMissing[0])
      return
    }
    const { input, context } = form.buildInput(complete)
    save.mutate(input, {
      onSuccess: () => {
        allowLeaveRef.current = true
        toast(complete ? t.save.saved : t.save.draftSaved)
        void navigate(AFTER_SAVE_PATH)
      },
      onError: (error) => form.handleSaveError(error, context),
    })
  }

  return { save, extract, extractStartedAt, allowLeaveRef, runExtract, submit }
}
