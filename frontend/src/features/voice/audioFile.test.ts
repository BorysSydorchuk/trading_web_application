import { describe, expect, it } from 'vitest'
import {
  AUDIO_FILE_ACCEPT,
  audioMimeType,
  checkAudioFile,
  fileExtension,
  MAX_AUDIO_FILE_BYTES,
  withMimeType,
} from './audioFile'

describe('audioMimeType', () => {
  it.each([
    ['audio_2026-11-04_23-24-49.ogg', 'audio/ogg'],
    ['voice.opus', 'audio/ogg'],
    ['memo.m4a', 'audio/mp4'],
    ['note.mp3', 'audio/mpeg'],
    ['note.wav', 'audio/wav'],
    ['note.webm', 'audio/webm'],
  ])('%s → %s', (name, mime) => {
    expect(audioMimeType(name)).toBe(mime)
  })

  it('ignores the case of the extension', () => {
    expect(audioMimeType('AUDIO.OGG')).toBe('audio/ogg')
    expect(audioMimeType('Memo.M4A')).toBe('audio/mp4')
  })

  it('uses the last extension only', () => {
    expect(audioMimeType('trade.ogg.txt')).toBeNull()
    expect(audioMimeType('notes.v2.mp3')).toBe('audio/mpeg')
  })

  it('rejects unknown, missing and empty extensions', () => {
    expect(audioMimeType('clip.mp4')).toBeNull()
    expect(audioMimeType('voice.flac')).toBeNull()
    expect(audioMimeType('screenshot.png')).toBeNull()
    expect(audioMimeType('ogg')).toBeNull()
    expect(audioMimeType('voice.')).toBeNull()
    expect(audioMimeType('')).toBeNull()
  })

  it('does not treat object keys as formats', () => {
    expect(audioMimeType('x.constructor')).toBeNull()
    expect(audioMimeType('x.toString')).toBeNull()
  })
})

describe('fileExtension', () => {
  it('lower-cases the part after the last dot', () => {
    expect(fileExtension('a.b.OPUS')).toBe('opus')
    expect(fileExtension('noext')).toBe('')
  })
})

describe('checkAudioFile', () => {
  it('accepts a Telegram voice note', () => {
    expect(checkAudioFile({ name: 'audio_2026-11-04_23-24-49.ogg', size: 48_213 })).toEqual({
      ok: true,
      mimeType: 'audio/ogg',
    })
  })

  it('accepts exactly 25 MiB and rejects one byte more', () => {
    expect(MAX_AUDIO_FILE_BYTES).toBe(26_214_400)
    expect(checkAudioFile({ name: 'a.wav', size: 26_214_400 })).toEqual({ ok: true, mimeType: 'audio/wav' })
    expect(checkAudioFile({ name: 'a.wav', size: 26_214_401 })).toEqual({ ok: false, error: 'too_large' })
  })

  it('rejects an empty file', () => {
    expect(checkAudioFile({ name: 'a.ogg', size: 0 })).toEqual({ ok: false, error: 'empty' })
  })

  it('reports the wrong format before the size', () => {
    expect(checkAudioFile({ name: 'video.mov', size: 0 })).toEqual({ ok: false, error: 'format' })
    expect(checkAudioFile({ name: 'video.mov', size: 30_000_000 })).toEqual({ ok: false, error: 'format' })
  })
})

describe('withMimeType', () => {
  it('rebuilds the blob with the upload type and keeps the bytes', async () => {
    const file = new File(['OggS-bytes'], 'voice.opus', { type: '' })
    const blob = withMimeType(file, 'audio/ogg')
    expect(blob.type).toBe('audio/ogg')
    expect(await blob.text()).toBe('OggS-bytes')
  })

  it('replaces an odd browser type', () => {
    const file = new File(['x'], 'memo.m4a', { type: 'audio/x-m4a' })
    expect(withMimeType(file, 'audio/mp4').type).toBe('audio/mp4')
  })
})

describe('AUDIO_FILE_ACCEPT', () => {
  it('lists every accepted extension and audio/*', () => {
    expect(AUDIO_FILE_ACCEPT).toBe('.ogg,.opus,.m4a,.mp3,.wav,.webm,audio/*')
  })
})
