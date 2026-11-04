# M3 QA stand-in audio (TTS)

Generated audio is not committed (scratch only). To regenerate on Windows:

    powershell -NoProfile -ExecutionPolicy Bypass -File tts.ps1 -In note_30s.txt  -Out note_30s.wav            # 30.3 s
    powershell -NoProfile -ExecutionPolicy Bypass -File tts.ps1 -In note_1min.txt -Out note_1min.wav           # 64.0 s
    powershell -NoProfile -ExecutionPolicy Bypass -File tts.ps1 -In note_2min.txt -Out note_2min.wav -Rate 2   # 123.1 s
    cd ..\..\..\backend
    uv run python ..\docs\reports\M3-qa-audio\towebm.py <in.wav> <out.webm>   # Opus 48 kHz mono, PyAV

Voice: "Microsoft Irina Desktop" (ru-RU, SAPI 5), 16 kHz 16-bit mono WAV. No Ukrainian voice is
installed, so the texts are Russian trading talk with English terms (FVG, IFVG, BOS, SMT, POI, QM).
The app transcribes with `WHISPER_LANGUAGE=uk`, so this is Russian speech decoded as Ukrainian:
see docs/reports/M3-qa.md for why that makes the timings pessimistic and noisy.

`e2e_timing.py <trade_id> <file> <content-type> [extract]`: uploads to a running app
(http://127.0.0.1:8000), polls `GET /api/audio/{id}` every 0.5 s, prints upload→done time,
then optionally times `POST /api/trades/{id}/extract` on the transcript.
