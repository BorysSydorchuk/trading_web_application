import { useUploadTradeAudio } from '@/features/voice/api'
import type { AudioNote } from '@/features/voice/types'
import { VoiceNotes } from '@/features/voice/VoiceNotes'
import { uk } from '@/i18n/uk'

const LABELS = {
  title: uk.describe.voice.title,
  listLabel: uk.describe.voice.listLabel,
  hint: uk.describe.voice.hint,
}

interface DescribeVoiceProps {
  tradeId: number
  /** TradeDetail.audio_notes when the page opened (oldest first). */
  tradeNotes: readonly AudioNote[]
  /** Append a transcript to the description text box. */
  onTranscript: (transcript: string) => void
  /** True while a recording exists only in the browser (uploading or upload failed). */
  onUnsentChange: (unsent: boolean) => void
}

/** Recorder + this trade's voice notes (the shared VoiceNotes with the trade upload). */
export function DescribeVoice({ tradeId, tradeNotes, onTranscript, onUnsentChange }: DescribeVoiceProps) {
  const upload = useUploadTradeAudio(tradeId)
  return (
    <VoiceNotes
      initialNotes={tradeNotes}
      upload={upload}
      onTranscript={onTranscript}
      onUnsentChange={onUnsentChange}
      labels={LABELS}
    />
  )
}
