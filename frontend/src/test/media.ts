/**
 * Fake microphone for component tests: `navigator.mediaDevices.getUserMedia` and `MediaRecorder`
 * (jsdom has neither). `controlClock()` moves Date.now forward so a hold can last "1.5 s" at once.
 */
import { vi } from 'vitest'

/** What the fake recorder "records". */
export const FAKE_AUDIO = 'fake-opus-audio'

export class FakeMediaRecorder {
  static instances: FakeMediaRecorder[] = []
  static isTypeSupported = (type: string): boolean => type.startsWith('audio/webm')

  state: 'inactive' | 'recording' = 'inactive'
  readonly mimeType: string
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null

  readonly stream: MediaStream

  constructor(stream: MediaStream, options?: { mimeType?: string }) {
    this.stream = stream
    this.mimeType = options?.mimeType ?? 'audio/webm'
    FakeMediaRecorder.instances.push(this)
  }

  start(): void {
    this.state = 'recording'
  }

  /** Like the browser: data first, then stop, asynchronously. */
  stop(): void {
    this.state = 'inactive'
    window.setTimeout(() => {
      this.ondataavailable?.({ data: new Blob([FAKE_AUDIO], { type: this.mimeType }) })
      this.onstop?.()
    }, 0)
  }
}

export interface FakeMic {
  getUserMedia: ReturnType<typeof vi.fn>
  /** stop() of the single audio track: called when the microphone is released. */
  stopTrack: ReturnType<typeof vi.fn>
}

/** Installs a working microphone, or one whose getUserMedia rejects with `reject`. */
export function installMic(options: { reject?: unknown } = {}): FakeMic {
  const stopTrack = vi.fn()
  const stream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream
  const getUserMedia = vi.fn(() =>
    options.reject === undefined ? Promise.resolve(stream) : Promise.reject(options.reject),
  )
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
  FakeMediaRecorder.instances = []
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  return { getUserMedia, stopTrack }
}

/** A browser without navigator.mediaDevices (insecure context, very old browser). */
export function removeMic(): void {
  Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true })
}

/** Call in afterEach. */
export function restoreMic(): void {
  Reflect.deleteProperty(navigator, 'mediaDevices')
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
}

export function denied(name = 'NotAllowedError'): DOMException {
  return new DOMException('Permission denied', name)
}

/** Date.now that can jump forward (everything else keeps real time). */
export function controlClock() {
  const realNow = Date.now.bind(Date)
  let offset = 0
  vi.spyOn(Date, 'now').mockImplementation(() => realNow() + offset)
  return {
    advance: (ms: number) => {
      offset += ms
    },
  }
}
