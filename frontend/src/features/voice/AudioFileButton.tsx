import { useId, useRef, type ChangeEvent } from 'react'
import { FileAudio } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { uk } from '@/i18n/uk'
import { AUDIO_FILE_ACCEPT } from './audioFile'

const t = uk.voice.recorder

interface AudioFileButtonProps {
  onFile: (file: File) => void
  disabled: boolean
}

/** "Завантажити аудіо": a real button that opens the hidden file input (keyboard accessible). */
export function AudioFileButton({ onFile, disabled }: AudioFileButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const hintId = useId()

  function onChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0]
    // Reset so picking the same file again fires `change` again.
    event.currentTarget.value = ''
    if (file) onFile(file)
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        aria-describedby={hintId}
        onClick={() => inputRef.current?.click()}
      >
        <FileAudio aria-hidden />
        {t.pickFile}
      </Button>
      <span id={hintId} className="sr-only">
        {t.pickFileHint}
      </span>
      <input
        ref={inputRef}
        type="file"
        accept={AUDIO_FILE_ACCEPT}
        className="hidden"
        tabIndex={-1}
        aria-hidden
        disabled={disabled}
        onChange={onChange}
        data-testid="audio-file-input"
      />
    </>
  )
}
