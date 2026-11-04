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
  /** With `hold: true`: opens the pending microphone request. */
  grant: () => void
}

interface MicOptions {
  /** getUserMedia rejects with this. */
  reject?: unknown
  /** getUserMedia stays pending until `grant()` (the permission prompt is still open). */
  hold?: boolean
}

/** Installs a working microphone, one whose getUserMedia rejects, or one that waits for `grant()`. */
export function installMic(options: MicOptions = {}): FakeMic {
  const stopTrack = vi.fn()
  const stream = { getTracks: () => [{ stop: stopTrack }] } as unknown as MediaStream
  let grant: () => void = () => undefined
  const getUserMedia = vi.fn(() => {
    if (options.reject !== undefined) return Promise.reject(options.reject)
    if (!options.hold) return Promise.resolve(stream)
    return new Promise<MediaStream>((resolve) => {
      grant = () => resolve(stream)
    })
  })
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
  FakeMediaRecorder.instances = []
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder)
  return { getUserMedia, stopTrack, grant: () => grant() }
}

/** The recorder created by the last press. */
export function lastRecorder(): FakeMediaRecorder {
  const recorder = FakeMediaRecorder.instances.at(-1)
  if (!recorder) throw new Error('no MediaRecorder was created')
  return recorder
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
