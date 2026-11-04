import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { uk } from '@/i18n/uk'
import { controlClock, denied, FAKE_AUDIO, installMic, removeMic, restoreMic } from '@/test/media'
import { VoiceRecorder } from './VoiceRecorder'

const t = uk.voice.recorder

function setup() {
  const onRecorded = vi.fn()
  const user = userEvent.setup()
  render(<VoiceRecorder onRecorded={onRecorded} />)
  return { user, onRecorded, button: screen.getByRole('button', { name: t.hold }) }
}

afterEach(restoreMic)

describe('VoiceRecorder', () => {
  it('records while the button is held and hands over a webm blob', async () => {
    const mic = installMic()
    const clock = controlClock()
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    expect(await screen.findByText(t.recording)).toBeInTheDocument()
    expect(button).toHaveAttribute('aria-pressed', 'true')
    clock.advance(2_500)
    await user.pointer({ keys: '[/MouseLeft]', target: button })

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
    const [blob, seconds] = onRecorded.mock.calls[0] as [Blob, number]
    expect(blob.type).toBe('audio/webm')
    expect(await blob.text()).toBe(FAKE_AUDIO)
    expect(seconds).toBeGreaterThanOrEqual(2.5)
    expect(mic.getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(mic.stopTrack).toHaveBeenCalled()
    expect(button).toHaveAttribute('aria-pressed', 'false')
  })

  it('records while Space is held on the focused button', async () => {
    installMic()
    const clock = controlClock()
    const { user, onRecorded, button } = setup()

    button.focus()
    await user.keyboard('[Space>]')
    expect(await screen.findByText(t.recording)).toBeInTheDocument()
    clock.advance(1_500)
    await user.keyboard('[/Space]')

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
  })

  it('discards a press shorter than 1 s with a hint and frees the microphone', async () => {
    const mic = installMic()
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await user.pointer({ keys: '[/MouseLeft]', target: button })

    expect(await screen.findByText(t.tooShort)).toBeInTheDocument()
    await waitFor(() => expect(mic.stopTrack).toHaveBeenCalled())
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('explains a denied microphone permission', async () => {
    installMic({ reject: denied() })
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await user.pointer({ keys: '[/MouseLeft]', target: button })

    expect(await screen.findByRole('alert')).toHaveTextContent(t.errors.denied)
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('explains a missing microphone', async () => {
    installMic({ reject: denied('NotFoundError') })
    const { user, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })

    expect(await screen.findByRole('alert')).toHaveTextContent(t.errors.no_mic)
  })

  it('explains a browser without mediaDevices', async () => {
    removeMic()
    const { user, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })

    expect(await screen.findByRole('alert')).toHaveTextContent(t.errors.no_mic)
  })

  it('does not start while disabled', async () => {
    const mic = installMic()
    const user = userEvent.setup()
    render(<VoiceRecorder onRecorded={vi.fn()} disabled />)
    const button = screen.getByRole('button', { name: t.hold })

    expect(button).toBeDisabled()
    await user.pointer({ keys: '[MouseLeft>]', target: button })
    expect(mic.getUserMedia).not.toHaveBeenCalled()
  })
})
