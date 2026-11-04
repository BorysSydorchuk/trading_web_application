import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { uk } from '@/i18n/uk'
import {
  controlClock,
  denied,
  FAKE_AUDIO,
  FakeMediaRecorder,
  installMic,
  lastRecorder,
  removeMic,
  restoreMic,
} from '@/test/media'
import { MAX_RECORDING_MS } from './recorderModel'
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

    expect(await screen.findByText(t.notices.tooShort)).toBeInTheDocument()
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

  it('stops by itself after 10 minutes and keeps the recording', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const mic = installMic()
      const onRecorded = vi.fn()
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      render(<VoiceRecorder onRecorded={onRecorded} />)
      const button = screen.getByRole('button', { name: t.hold })

      await user.pointer({ keys: '[MouseLeft>]', target: button })
      expect(await screen.findByText(t.recording)).toBeInTheDocument()
      await act(() => vi.advanceTimersByTimeAsync(MAX_RECORDING_MS))

      await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
      expect(onRecorded.mock.calls[0]?.[1]).toBeGreaterThanOrEqual(MAX_RECORDING_MS / 1000)
      expect(screen.getByText(t.notices.maxReached)).toBeInTheDocument()
      expect(mic.stopTrack).toHaveBeenCalled()
      // Letting go afterwards does not start or send anything.
      await user.pointer({ keys: '[/MouseLeft]', target: button })
      expect(onRecorded).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('drops the recording and frees the mic when unmounted while recording', async () => {
    const mic = installMic()
    const onRecorded = vi.fn()
    const user = userEvent.setup()
    const { unmount } = render(<VoiceRecorder onRecorded={onRecorded} />)

    await user.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: t.hold }) })
    await screen.findByText(t.recording)
    unmount()

    expect(mic.stopTrack).toHaveBeenCalled()
    await new Promise((resolve) => window.setTimeout(resolve, 20))
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('frees the mic granted after an unmount during the permission prompt', async () => {
    const mic = installMic({ hold: true })
    const onRecorded = vi.fn()
    const user = userEvent.setup()
    const { unmount } = render(<VoiceRecorder onRecorded={onRecorded} />)

    await user.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: t.hold }) })
    expect(await screen.findByText(t.starting)).toBeInTheDocument()
    unmount()
    await act(async () => mic.grant())

    await waitFor(() => expect(mic.stopTrack).toHaveBeenCalled())
    expect(FakeMediaRecorder.instances).toHaveLength(0)
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('treats a release during the permission prompt as a short press', async () => {
    const mic = installMic({ hold: true })
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await user.pointer({ keys: '[/MouseLeft]', target: button })
    await act(async () => mic.grant())

    expect(await screen.findByText(t.notices.tooShort)).toBeInTheDocument()
    expect(mic.stopTrack).toHaveBeenCalled()
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('stops on pointercancel (e.g. the browser takes over the touch)', async () => {
    installMic()
    const clock = controlClock()
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await screen.findByText(t.recording)
    clock.advance(1_500)
    fireEvent.pointerCancel(button)

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
  })

  it('stops when the pointer leaves the button without capture', async () => {
    installMic()
    const clock = controlClock()
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await screen.findByText(t.recording)
    clock.advance(1_500)
    fireEvent.pointerLeave(button)

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
  })

  it('stops when the focused button loses focus while Space is held', async () => {
    installMic()
    const clock = controlClock()
    const { user, onRecorded, button } = setup()

    button.focus()
    await user.keyboard('[Space>]')
    await screen.findByText(t.recording)
    clock.advance(1_500)
    act(() => button.blur())

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
  })

  it('shows a recorder error when the browser fails a short recording', async () => {
    const mic = installMic()
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await screen.findByText(t.recording)
    act(() => lastRecorder().onerror?.())

    expect(await screen.findByRole('alert')).toHaveTextContent(t.errors.recorder)
    expect(mic.stopTrack).toHaveBeenCalled()
    expect(onRecorded).not.toHaveBeenCalled()
  })

  it('keeps what was recorded when the browser fails after 1 s', async () => {
    installMic()
    const clock = controlClock()
    const { user, onRecorded, button } = setup()

    await user.pointer({ keys: '[MouseLeft>]', target: button })
    await screen.findByText(t.recording)
    clock.advance(2_000)
    act(() => lastRecorder().onerror?.())

    await waitFor(() => expect(onRecorded).toHaveBeenCalledTimes(1))
    expect(screen.getByText(t.notices.interrupted)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
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
