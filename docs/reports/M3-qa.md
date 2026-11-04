# M3-09 QA: voice input

Date: 2026-11-04 (evening, 22:35–23:06 Brussels). Branch: `main` at 13afae1 (all M3 code merged).
Tester: qa-tester agent. No product code changed.

## Environment

- Borys's laptop: Intel Core i5-13500H (12 cores: 4 P + 8 E, 16 threads), 15.7 GB RAM, Windows 11 Home 10.0.26200,
  on AC power, power plan "Razer Cortex Power Plan". TradingView and Chrome were open (idle, < 0.1 core).
- faster-whisper 1.2.1, PyAV 18.1.0, CPU only. Defaults from settings: `small`, `int8`, language `uk`,
  beam 5, cpu threads 0 (library default), VAD on, glossary `initial_prompt` from config/transcription.yaml.
- `small` was already cached; `base` downloaded in this run (load 7.9 s incl. download).
- End-to-end runs used an **isolated QA database** `trading_journal_qa_m3` (same Postgres container),
  `MT5_SOURCE=fixture:backend/tests/fixtures/mt5/basic_week.json`, `DATA_DIR=<scratch>/data`, all passed as
  process env vars (no .env edit). Reason: the app never deletes audio notes, so test notes on Borys's real
  trades would stay in his journal. Real DB checked afterwards: 0 audio notes, requirements table unchanged.
- `ANTHROPIC_API_KEY` is configured (the worker's AI warm-up succeeded at start, `GET /api/ai/usage`
  `configured: true`), so extraction was timed live (Sonnet 5.5).

## Audio used (stand-in, not real speech)

No Ukrainian TTS voice is installed (SAPI: Irina ru-RU, Zira en-US; OneCore: Irina, Pavel ru-RU). I used
**Microsoft Irina Desktop (ru-RU)** reading Russian trading talk with English terms (FVG, IFVG, BOS, SMT, POI, QM,
GER40, XAUUSD, EURUSD), 16 kHz mono WAV, converted to WebM/Opus 48 kHz mono with PyAV (what the browser uploads).
Sources and generator: `docs/reports/M3-qa-audio/` (audio itself not committed).

| file | duration | words | note |
|---|---|---|---|
| note_30s | 30.3 s | 49 | rate 0 |
| note_1min | 64.0 s | 111 | rate 0 |
| note_2min | 123.1 s | 275 | rate +2 (≈ 134 words/min, denser than calm speech, so pessimistic) |
| corrupt.webm | – | – | 50 000 random bytes |
| truncated.webm | – | – | first 200 bytes of note_30s.webm |
| silence.wav | 5.0 s | – | digital silence |

**Caveat that matters for the numbers:** this is Russian speech decoded with `language=uk`. Whisper's
quality checks (avg log-prob / compression ratio) fail more often on such a mismatch, which triggers its
temperature fallback (re-decoding the window at temperature 0.2…1.0 with best_of 5). That makes the
timings slower and much noisier than for real Ukrainian speech is likely to be (see "Fallback check").
The final AC numbers must come from Borys's own recordings.

## Timings

`make whisper-bench` "transcription" = decode + transcribe (model load excluded, printed separately).
Cold = first file in a fresh process (includes first-inference warm-up), warm = same file again in that
process. RTF = transcription s / audio s. Extraction = `POST /api/trades/{id}/extract` on the transcript.

### A. Bench, default settings (machine cool, 22:36–22:41)

| model | audio | load s | cold transcr. s (RTF) | warm transcr. s (RTF) | + extraction ~2.2 s | vs 30 s |
|---|---|---|---|---|---|---|
| small int8 b5 | 30.3 s | 2.0 | 8.1 (0.27) | 7.6 (0.25) | ≈ 10 s | pass |
| small int8 b5 | 64.0 s | 1.2 | 17.4 (0.27) | 17.0 (0.27) | ≈ 19 s | pass |
| small int8 b5 | 123.1 s | 1.2 | 44.8 (0.36) | 45.3 (0.37) | **≈ 47 s** | **FAIL** |
| base int8 b5 | 30.3 s | 7.9 (download) | 4.8 (0.16) | 5.0 (0.17) | ≈ 7 s | pass |
| base int8 b5 | 64.0 s | 0.7 | 15.6 (0.24) | 29.9 (0.47) | 18–32 s | borderline |
| base int8 b5 | 123.1 s | 0.7 | 38.1 (0.31) | 46.1 (0.37) | **40–48 s** | **FAIL** |

`base` with beam 5 is **not** meaningfully faster than `small` on this audio (fallback-driven, see below).

### B. End to end through the running app, default settings (22:49–22:53)

`make dev`-equivalent launcher (`scripts/dev.py`), upload with `POST /api/trades/{id}/audio`
(`audio/webm`), poll `GET /api/audio/{id}` every 0.5 s, then extract. Worker numbers from its INFO line.

| note | audio | upload | upload → done | worker transcr. s / wall s (RTF) | extraction | total vs 30 s |
|---|---|---|---|---|---|---|
| 1 (first after worker start, cold) | 30.3 s | 0.06 s | 17.6 s | 14.5 / 16.8 (0.48) | 2.2 s (3 fields) | 19.8 s pass |
| 2 | 64.0 s | 0.04 s | 26.1 s | 25.2 / 25.2 (0.39) | 1.7 s (2 fields) | 27.7 s pass (barely) |
| 3 | 123.1 s | 0.04 s | 69.7 s | 68.9 / 68.9 (0.56) | 2.2 s (3 fields) | **71.9 s FAIL** |
| 4 (repeat) | 123.1 s | 0.04 s | 69.4 s | 68.7 / 68.7 (0.56) | 2.2 s | **71.6 s FAIL** |

Queue overhead (pending → processing) was 0.6–1.1 s (2 s job interval). Progress updated about once a second.

**The app was not slower than the bench**: right after these runs the bench on the same 2-min file took
75.3 s with the app idle and 69.5 s with the app stopped. The laptop had slowed down after ~15 min of
sustained full-CPU load (thermal/power limits): the same file and settings went 45 s → 69 s. Idle CPU of the
app (API + worker + Vite) measured < 0.1 core over 10 s. So a 2-min note on this laptop takes
**45 s (cool) to 70 s (warm laptop)** with the current defaults.

### C. Options on the 2-min note (only .env-level settings, passed as env vars)

| model | threads | beam | run 1 s (RTF) | run 2 s (RTF) | state |
|---|---|---|---|---|---|
| small | 8 | 5 | 55.1 (0.45) | 58.5 (0.48) | warming |
| small | auto | 1 | 33.2 (0.27) | 26.4 (0.21) | warming |
| small | 8 | 1 | 20.0 (0.16) | 19.4 (0.16) | warming |
| base | 8 | 5 | 30.5 (0.25) | 37.7 (0.31) | warming |
| base | 8 | 1 | 9.6 (0.08) | 9.8 (0.08) | warming |
| small | auto | 1 | 23.6 (0.19) | – | hot |
| base | auto | 1 | 6.6 (0.05) | – | hot |

But `small` beam 1 on the **30 s** note (hot laptop) took 39.3 s, 34.9 s, 27.7 s (RTF 0.9–1.3): greedy
decoding hit the fallback path. Beam 1 alone does not give a reliable bound.

### D. Fallback check (scratch script, faster-whisper directly, same prompt/VAD, 30 s note, `small`, hot laptop)

| beam | temperature | language | time |
|---|---|---|---|
| 1 | default (0…1 fallback) | uk | 60.9 s |
| 1 | 0 only (no fallback) | uk | 11.4 s |
| 1 | default | ru | 8.1 s |
| 5 | default | uk | 13.1 s |
| 5 | 0 only | uk | 7.6 s |
| 5 | default | ru | 12.5 s |

With the fallback switched off, or with the language matching the speech, the slow runs disappear. This
supports the guess that the language mismatch of the stand-in audio triggers the fallback. The app has no
setting for the temperature (it would need a code change, so it's for the PM, not a bug).

### Transcript quality (stand-in audio)

- `small` (beam 5 or 1, almost identical text): terms mostly right: GER40, XAUUSD, EURUSD, FVG, POI, QM, BOS,
  SMT; "4 з 5", "400 пунктов", "3R". Misses: IFVG → "АЕФ ВІДЖИ", "сессия" → "CCL"/"CCLONDON", "Flow" → "FLO".
  The output is a Russian/Ukrainian mix (as expected when Russian speech is forced to `uk`).
- `base`: clearly worse on terms: FVG → "як відже"/"Віджи", IFVG → "оєв відже"/"еквіджи", POI → "піло",
  SMT/GBPUSD → "SMTD вергенцію з WPSD", more broken words.
- Extraction on the 2-min transcript filled 3 fields vs 4 from the clean source text (one call each, 2.0 s /
  2.5 s); the low count is due to this text vs the enum options, not to transcription.

## Failure and retry (through the running app, QA DB)

| check | result |
|---|---|
| random bytes as `audio/webm` → 201 pending → `failed` / `audio_unreadable` in 4.5 s | pass |
| truncated webm (200 B) → `failed` / `audio_unreadable` in 1.1 s | pass |
| 5 s silence wav → `failed` / `no_speech`, `duration_seconds` "5.000" | pass |
| failed files kept in `<DATA_DIR>/audio/2026/11/<uuid>.<ext>`; `GET /api/audio/{id}/file` 200 with stored type, bytes identical to upload | pass |
| `POST /api/audio/5/retry` → 200 `pending`, error/progress/transcript cleared → `failed` / `audio_unreadable` again | pass |
| retry on a `done` note → 409 `audio_not_failed`; unknown note → 404 `not_found` | pass |
| stored file moved away: `GET .../file` → 404 `audio_missing`; retry → `failed` / `audio_missing`; restored + retry → back to `audio_unreadable`, file 200 | pass |
| valid audio placed at a failed note's stored path + retry → `done` with transcript (one-click recovery works) | pass |
| worker.log: one ERROR line per failed note with code and English detail; one INFO line per done note (audio s, transcription s, wall s, RTF) | pass |
| upload errors: text/plain 415 `unsupported_media_type`; empty 422; open trade 409 `trade_open` (with `;codecs=opus`); unknown trade 404; 27 MB 413 `audio_too_large`; `needs_sl` trade accepted | pass |
| uk.ts has `errors.transcription.<code>` for all six codes (audio_unreadable, audio_missing, no_speech, model_unavailable, timeout, transcription_failed), plus `audio_too_large`, `unsupported_media_type`, `audio_not_failed`, `audio_missing`, and recorder `denied` / `no_mic` / `unsupported` / `other` | pass (texts present; rendering not seen in a browser) |

Not tested: `model_unavailable` (needs breaking the HF cache / offline first download), `timeout` (> 600 s),
behaviour with no internet when the model is cached (every model load sends HEAD requests to huggingface.co;
I expect faster-whisper to fall back to the cache, but did not check).

## New required fields (API part, QA DB)

Temporarily set `lesson` `required: false → true` in config/journal_fields.yaml (line 161):
- `journal_field_requirements` got `lesson` with `required_since` = now (22:04:37Z) on the first API read.
- `GET /api/trades?missing_new_fields=true` → 6 closed trades; `GET /api/trades/1` → `missing_new_fields: ["lesson"]`,
  `lesson` not in `missing_required`; open trade 7 → `[]`.
- Restored the YAML from a byte copy (`cmp` identical, `git status` clean for that file); the row was deleted
  on the next read, filter → 0. Only the QA DB was touched.

## Browser checks

**Not done: no browser automation is available to me** (no Chrome tools, no Playwright/Puppeteer/Selenium
installed, and adding them needs approval). Left for Borys's live check below.

## Acceptance criteria

| AC | verdict | how verified |
|---|---|---|
| 2-minute voice note transcribed and fields prefilled in < 30 s on Borys's laptop | **FAIL with current defaults** (small int8 beam 5): 47 s (cool laptop, bench + extraction) to 72 s (app end to end, warm laptop). Stand-in TTS audio, so the final number needs Borys's voice. | make whisper-bench ×2 per length; app upload → poll → extract; worker.log |
| Failure of transcription shows a clear error and keeps the audio | **PASS on the API/worker side** (codes, kept files, replay, retry, uk texts present). The UI display is not seen in a browser yet. | API + worker runs above, uk.ts check |

## Bugs / findings

No blocking product bug found.

1. LOW (contract wording vs behaviour): api.md says `missing_new_fields` "`false`/absent = no filter; other
   values → 422", but FastAPI's bool parsing accepts `yes/no/on/off/1/0/TRUE` (200); only e.g. `foo` → 422.
   Repro: `curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/api/trades?missing_new_fields=yes"` → 200.
   Either relax the doc line or validate strictly; harmless either way.
2. LOW (docs): DECISIONS M3-04 says `make whisper-bench` prints "audio s / transcription s / wall s / RTF";
   it prints the model load once plus audio / transcription / RTF per file (no per-file wall column).
   The worker's INFO line does have wall s.
3. Not mine, needs attention: `.env.example` became modified in the working tree at 22:43:44 local time,
   while only my benchmarks were running. I never opened or edited it (read access is denied to me). It is
   left uncommitted; whoever changed it (another agent or Borys) should check it.
4. Observation: on this laptop the same 2-min note goes 45 s → 70 s after ~15 min of full CPU load; the
   AC margin has to cover a warm laptop, not only a cool one.

## Recommendation (for the PM)

- Do **not** switch to `base`: with beam 5 it is not faster on this audio (40–48 s for 2 min), and its term
  recognition is clearly worse (FVG/IFVG/POI broken). `base` beam 1 is very fast (7–10 s) but has the worst
  text.
- Keep `small`. The cheapest lever is `WHISPER_BEAM_SIZE=1` (.env only, no code): the 2-min note took 19–33 s
  with the same text quality, but greedy decoding hit the fallback spikes on the 30 s note (28–39 s), so it is
  not a guaranteed bound.
- If Borys's real 2-min Ukrainian note is still > 30 s: a code change that limits the temperature fallback
  (e.g. temperature 0 only, or fewer steps) removed the spikes in D (60.9 s → 11.4 s). That's a PM/tech decision
  (quality trade-off on hard audio), not a bug.
- Before deciding: measure Borys's own 30 s / 1 min / 2 min recordings with
  `make whisper-bench FILES="..."` (small b5), then `WHISPER_BEAM_SIZE=1` and `WHISPER_MODEL=base`, each twice, once
  right after a quiet laptop and once after a few minutes of load. The stand-in Russian TTS with `language=uk` is
  probably pessimistic.

## Left for Borys (live, in the browser)

1. Describe screen: hold-to-record (pointer and Space/Enter), < 1 s hint, upload, progress bar, transcript
   auto-inserted into the text box once, "Вставити в текст" for notes done before the page opened, replay of
   done/failed notes, "Заповнити з тексту" afterwards.
2. Mic denied (block the mic for 127.0.0.1:5173 in Chrome) → the `denied` message, text input still works;
   no mic → `no_mic` message.
3. A failed note in the UI: Ukrainian error text per code, replay works, "retry" button → pending → result.
   (Upload any non-audio file renamed .webm via the API, or use the QA DB below.)
4. Failed upload (stop the API mid-upload): kept blob, "Завантажити ще раз" / "Видалити запис", recorder disabled.
5. Journal filter "Неповні за новими полями" and the Describe note for new required fields (toggle a field
   `required: true` on a trade closed earlier, check, then revert the YAML exactly; un-requiring deletes the row).
6. Real 2-min voice timing as above (the AC number).

The QA database `trading_journal_qa_m3` (fixture account, 7 trades, 7 audio notes) is left in the Postgres
container for these checks: start with `DATABASE_URL=postgresql+psycopg://journal:journal@127.0.0.1:5432/trading_journal_qa_m3`,
`MT5_SOURCE=fixture:backend/tests/fixtures/mt5/basic_week.json`, `MT5_PASSWORD_51234567=qa`, `DATA_DIR=<some scratch dir>`
as process env vars. Note: the audio files of those 7 notes were in my scratch dir and will be gone, so they show
`audio_missing` on replay. Drop it with `DROP DATABASE trading_journal_qa_m3` when done.
