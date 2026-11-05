/** Save / delete / extract / create-for-voice of the bias note editor. */
import { useRef, useState, type RefObject } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ApiError, isApiError } from '@/api/client'
import { uk } from '@/i18n/uk'
import { showErrorToast } from '@/lib/errors'
import { biasKeys, createBiasNote, useBiasExtract, useDeleteBiasNote, useSaveBiasNote } from './api'
import type { BiasNote } from './types'
import type { BiasForm } from './useBiasForm'

const e = uk.bias.editor
const LIST_PATH = '/bias'

function existingIdOf(error: unknown): number | null {
  if (!isApiError(error) || error.code !== 'bias_note_exists') return null
  const id = error.details?.id
  return typeof id === 'number' ? id : null
}

/** Scrolls to and focuses the first marked field of the editor (after the error render). */
function focusFirstError() {
  const element = document.querySelector<HTMLElement>('[data-bias-editor] [aria-invalid="true"]')
  if (!element) return
  element.scrollIntoView({ block: 'center', behavior: 'smooth' })
  const focusable = element.matches('input, textarea') ? element : element.querySelector<HTMLElement>('button')
  focusable?.focus({ preventScroll: true })
}

interface ActionsArgs {
  form: BiasForm
  initialNoteId: number | null
  /** True while a recording exists only in the browser; a save then stays on the page. */
  unsentRecordingRef: RefObject<boolean>
  /** A note was created on this page (for voice, or by a save that stays): the page keeps this editor. */
  onCreated: (note: BiasNote) => void
}

export function useBiasActions({ form, initialNoteId, unsentRecordingRef, onCreated }: ActionsArgs) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const save = useSaveBiasNote()
  const remove = useDeleteBiasNote()
  const extract = useBiasExtract()
  const [noteId, setNoteId] = useState(initialNoteId)
  const noteIdRef = useRef(initialNoteId)
  /** Set right before an intended navigation, so the unsaved-changes guard lets it through. */
  const allowLeaveRef = useRef(false)
  const [extractStartedAt, setExtractStartedAt] = useState<number | null>(null)

  /** Switches the editor to the new note and its URL (/bias/new → /bias/<id>), keeping all edits. */
  function adopt(note: BiasNote) {
    noteIdRef.current = note.id
    setNoteId(note.id)
    queryClient.setQueryData(biasKeys.detail(note.id), note)
    onCreated(note)
    allowLeaveRef.current = true
    void Promise.resolve(navigate(`${LIST_PATH}/${note.id}`, { replace: true })).finally(() => {
      allowLeaveRef.current = false
    })
  }

  /** The note id for a voice upload; a new note is created first with entries [] (DECISIONS M4-05). */
  async function ensureNoteId(): Promise<number> {
    if (noteIdRef.current !== null) return noteIdRef.current
    if (!form.dateValid) {
      form.setAttempted(true)
      throw new ApiError('validation_error', 'period_date', 422, { fields: { period_date: 'invalid' } })
    }
    const { input } = form.buildInput()
    try {
      const note = await createBiasNote({ ...input, entries: [] })
      adopt(note)
      void queryClient.invalidateQueries({ queryKey: biasKeys.lists })
      toast(e.createdForVoice, { id: 'bias-created-for-voice' })
      return note.id
    } catch (error) {
      form.showExisting(existingIdOf(error))
      throw error
    }
  }

  function runExtract() {
    const text = form.rawText.trim()
    if (text === '') return
    setExtractStartedAt(Date.now())
    extract.mutate(
      { kind: form.kind, text },
      { onSuccess: (result) => form.applyExtraction(result), onSettled: () => setExtractStartedAt(null) },
    )
  }

  function leaveToList(message: string) {
    allowLeaveRef.current = true
    toast(message)
    void navigate(LIST_PATH)
  }

  function submit() {
    form.setAttempted(true)
    if (form.hasClientErrors) {
      toast.error(e.fixErrors, { id: 'bias-client-errors' })
      requestAnimationFrame(focusFirstError)
      return
    }
    const { input, sent } = form.buildInput()
    if (noteIdRef.current === null && input.entries.length === 0 && input.raw_text === null) {
      toast.error(e.nothingToSave, { id: 'bias-nothing-to-save' })
      return
    }
    const wasNew = noteIdRef.current === null
    save.mutate(
      { id: noteIdRef.current, input },
      {
        onSuccess: (note) => {
          // Checked when the save lands: the upload may have finished or failed meanwhile.
          if (!unsentRecordingRef.current) return leaveToList(e.saved)
          if (wasNew) adopt(note)
          toast(e.savedRecordingUnsent, { id: 'bias-saved-recording-unsent' })
        },
        onError: (error) => {
          form.handleSaveError(error, sent)
          showErrorToast(error)
        },
      },
    )
  }

  function deleteNote(onDone: () => void) {
    const id = noteIdRef.current
    if (id === null) return
    remove.mutate(id, {
      onSuccess: () => {
        onDone()
        allowLeaveRef.current = true
        toast(e.deleted)
        // Dropped once the editor is gone, so the deleted note is not refetched (404) meanwhile.
        void Promise.resolve(navigate(LIST_PATH)).then(() => queryClient.removeQueries({ queryKey: biasKeys.detail(id) }))
      },
      onError: showErrorToast,
    })
  }

  return { noteId, save, remove, extract, extractStartedAt, allowLeaveRef, ensureNoteId, runExtract, submit, deleteNote }
}

export type BiasActions = ReturnType<typeof useBiasActions>
