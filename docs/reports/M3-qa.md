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

## M3-13 Timing on Borys's recordings

Date: 2026-11-05, 09:06–09:26 Brussels. Branch `main` at becfb0d (all M3 code incl. M3-11 Whisper settings
merged). Tester: qa-tester agent. No product code changed.

### Method

- Recordings: `data/qa-voice/` (Borys's Telegram voice notes, .ogg Opus 48 kHz mono, gitignored, not copied).
  Decoded durations: **A = 19.0 s**, **B = 40.7 s**, **C = 82.4 s** (`audio_2026-11-04_23-24-49`, `…23-25-18`,
  `…23-25-00`). Silero VAD removed 0 s / 7.6 s / 15.7 s of silence. There is no 2-min recording.
- Through the running app: API (uvicorn, started once) + a fresh worker per (round, config), QA DB
  `trading_journal_qa_m3`, fixture MT5 source, scratch `DATA_DIR` and `LOG_DIR`, trade 6 (closed, SL set).
  Every `WHISPER_*` value (model `small`, `int8`, `uk`, beam, vad, condition_on_previous_text, temperatures,
  cpu threads) was set in the process environment, so Borys's `.env` (beam 5, threads 0) did not leak in;
  the worker's INFO line confirms the settings of every note.
- Per run: `POST /api/trades/6/audio` (audio/ogg) → poll `GET /api/audio/{id}` every 0.25 s until `done` →
  `POST /api/trades/6/extract` on the transcript. "upload→done" includes the upload (≤ 0.07 s) and the queue
  wait (2 s job interval). "transcr." = the worker's transcription seconds (decode + transcribe, no model load).
- **Model kept loaded**: after each worker start one warm-up note (A) was transcribed and discarded
  (it includes the model load: wall 10–17 s). Times below never include a model load.
- 3 rounds; in each round the 6 configs ran in a shuffled order (seed 20261105) and the 3 files in a
  shuffled order inside each worker session (driver: `docs/reports/M3-qa-audio/matrix.py`). Median of 3.
- Configs: **old** = beam N, vad on, condition_on_previous_text on, temperatures 0,0.2,…,1.0, threads 0
  (library default). **new** = beam N, vad on, condition off, temperatures 0.0,0.4, threads auto (12
  physical cores detected). **newcond** = new + condition_on_previous_text on (extra config for the PM).
- Thermal: `typeperf` every 5 s. ACPI zone temperature 79–96 °C during the whole matrix (≈ 95 °C under load),
  `% Passive Limit` 100 (no ACPI passive throttling reported), `% Processor Performance` steady 116–123 %
  (≈ 3.0–3.2 GHz of the 2.6 GHz base) in every run. The laptop was already at its hot steady state at the
  start (a reference bench ran just before), so this is the **warm-laptop** case from M3-09; the three
  rounds of a cell differ by ≤ 2.5 s, so there was no drift between early and late cells.

### AI fill could not be measured: the configured key is rejected

All 54 `POST /api/trades/6/extract` calls returned **502 `ai_error` / `auth`** after 0.2 s
(`AuthenticationError HTTP 401 … invalid x-api-key`, logged as ERROR in api.log: the error is visible, no
silent failure). The same key worked on 2026-11-04 21:48 UTC (worker AI warm-up in logs/worker.log). It
comes from `.env`, which I can't read; `ANTHROPIC_API_KEY` is not set in my shell. Repro (app running):
`curl -s -X POST http://127.0.0.1:8000/api/trades/6/extract -H "Content-Type: application/json" -d '{"text":"Вхід через FVG"}'`
→ 502 `ai_error`, details.kind `auth`. Suspected cause: the key in `.env` was rotated/revoked or changed
(`.env.example` is also modified in the working tree, not by me). Not a product bug.

So "TOTAL" below = measured upload→done **+ 2.2 s AI fill (estimate: the median measured in M3-09, 1.7–2.5 s
on transcripts of similar length, same model `claude-sonnet-5-5`, effort low)**. Re-measure once the key works.

### Timings (median of 3; individual runs in brackets)

| file | config | transcr. s (RTF) | upload→done s | TOTAL s (+2.2 AI est.) |
|---|---|---|---|---|
| A 19.0 s | old b1 | 6.6 (0.35) | 7.9 [9.2/7.9/7.9] | 10.1 |
| A 19.0 s | old b5 | 11.5 (0.61) | 12.9 [12.9/13.7/12.2] | 15.1 |
| A 19.0 s | **new b1** | 6.4 (0.34) | 7.1 [6.8/7.1/8.5] | **9.3** |
| A 19.0 s | new b5 | 11.9 (0.63) | 13.7 [12.8/13.7/13.8] | 15.9 |
| A 19.0 s | newcond b1 | 6.4 (0.34) | 8.2 [7.9/8.2/8.2] | 10.4 |
| A 19.0 s | newcond b5 | 12.0 (0.63) | 13.3 [13.9/13.3/12.4] | 15.5 |
| B 40.7 s | old b1 | 10.9 (0.27) | 11.6 [11.6/11.9/11.6] | 13.8 |
| B 40.7 s | old b5 | 16.2 (0.40) | 17.0 [16.9/17.0/17.1] | 19.2 |
| B 40.7 s | **new b1** | 9.6 (0.24) | 10.7 [10.7/10.9/10.5] | **12.9** |
| B 40.7 s | new b5 | 13.9 (0.34) | 14.5 [13.7/15.2/14.5] | 16.7 |
| B 40.7 s | newcond b1 | 10.5 (0.26) | 11.9 [11.9/12.3/11.3] | 14.1 |
| B 40.7 s | newcond b5 | 16.8 (0.41) | 18.0 [20.4/17.9/18.0] | 20.2 |
| C 82.4 s | old b1 | 19.9 (0.24) | 20.4 [20.2/21.3/20.4] | 22.6 |
| C 82.4 s | old b5 | 34.9 (0.42) | 36.4 [34.9/36.7/36.4] | 38.6 |
| C 82.4 s | **new b1** | 17.0 (0.21) | 18.4 [18.9/17.7/18.4] | **20.6** |
| C 82.4 s | new b5 | 28.5 (0.35) | 28.8 [28.5/28.8/31.0] | 31.0 |
| C 82.4 s | newcond b1 | 18.5 (0.22) | 19.9 [20.2/19.8/19.9] | 22.1 |
| C 82.4 s | newcond b5 | 34.6 (0.42) | 36.4 [36.8/36.0/36.4] | 38.6 |

`old b5` is what production ran before M3-11.

**ESTIMATE for a 120 s note** (not measured; C's RTF × 120 s + C's measured queue/upload overhead + 2.2 s AI):

| config | RTF (C) | transcr. 120 s | TOTAL 120 s (estimate) | vs 30 s |
|---|---|---|---|---|
| new b1 (new defaults) | 0.206 | 24.8 s | **≈ 28.4 s** | pass, 1.6 s margin |
| newcond b1 | 0.225 | 26.9 s | ≈ 30.5 s | borderline fail |
| old b1 | 0.242 | 29.0 s | ≈ 31.7 s | fail |
| new b5 | 0.346 | 41.5 s | ≈ 44.0 s | fail |
| newcond b5 / old b5 | 0.42 | 50.4 s | ≈ 54.5 s | fail |

Linear scaling of C's RTF is slightly pessimistic (shorter notes have a higher RTF because of a fixed per-note
cost: a straight line through B and C gives 23.7 s / 25.7 s transcription for new b1 / newcond b1, i.e.
≈ 27.3 s / 29.3 s TOTAL), but it depends on how much silence the 2-min note has (VAD skipped 19 % of C) and
on the real AI fill time.

### Terms (all 3 runs per cell; ✅ = correct in 3/3, otherwise the wrong form)

Only terms actually spoken. **No symbol names (EURUSD, GBPUSD, XAUUSD, GER40…) and no QM / BOS / SMT are spoken
in these three recordings** (none appears in any of the 72 transcripts), so they could not be checked.
I can't listen to the audio: the expected term is inferred from the agreement of the six configs and the
context; "FVG H1" in C is the least certain (heard as "POI FVH1").

| file | term | old b1 | old b5 | new b1 | new b5 | newcond b1 | newcond b5 |
|---|---|---|---|---|---|---|---|
| A | FTA | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| A | RR | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| A | MT5 (platform, info) | ❌ МТ5 (Cyrillic) | ❌ МТ-5/МТ5 | ❌ МТ5 | ❌ МТ-5/МТ5 | ❌ МТ5 | ❌ МТ5 |
| B | FVG | ❌ ФВГ | ✅ | ❌ фвг | ❌ фвг | ❌ ФВГ | ✅ |
| C | POI | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| C | FVG H1 (after POI) | ❌ FVG-1 ×2, FVH1 | ❌ FVH1 | ❌ FVH1 | ❌ FVH1 | ❌ FVH1 | ❌ FVH1 |
| C | FVG (2nd) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| C | H4 | ❌ "аж 4" ×2 (1 ✅) | ❌ "аж 4" ×1 (2 ✅) | ❌ "аж 4" | ❌ "аж 4" | ✅ | ✅ |
| C | H1 (setup) | ❌ "аж 1" ×2 (1 ✅) | ❌ "аж 1" ×1 (2 ✅) | ❌ "аж 1" | ❌ "аж 1" / "аж один" | ✅ | ✅ |
| C | Flow | ✅ | ✅ | ❌ флоу | ❌ флоу | ✅ | ✅ |
| C | IFVG | ✅ | ✅ | ❌ іфввг | ❌ іФВГ | ✅ | ✅ |
| C | M5 | ✅ | ✅ | ❌ м5 (Cyrillic) | ❌ М5 (Cyrillic) | ✅ | ✅ |
| C | FTA (×2) | ✅ | ✅ | ❌ ФТА | ❌ ФТА ×1 (2 ✅) | ✅ | ✅ |

With condition_on_previous_text **off**, every 30 s window after the first is decoded without the previous
text, so the Latin spellings primed by the glossary prompt are lost and terms later in the note come out
phonetic in Cyrillic (C's terms after ~60 s). With it **on**, the Latin forms carry through the whole note.

### Acceptance (PM 2026-11-04: 2-min note ≤ 30 s median with the new defaults AND terms correct)

| criterion | result |
|---|---|
| Time, new defaults (new b1), longest real note 82.4 s | **pass**: 18.4 s upload→done, ≈ 20.6 s with the estimated AI fill |
| Time, new defaults, 120 s (ESTIMATE from RTF) | ≈ 28.4 s: **pass by estimate**, thin margin, hot laptop |
| Terms, new defaults | **FAIL**: in C, IFVG, H4, H1, Flow, M5, FTA are wrong in 3/3 runs; in B, FVG → "фвг" |
| AI fill measured live | **not done**: AI key rejected (401), estimate used |

**Overall: FAIL** (terms). Per the PM rule I did not tune further.

### Recommendation (facts for the PM)

- **newcond b1** (`WHISPER_CONDITION_ON_PREVIOUS_TEXT=true`, rest of the new defaults) is the best trade-off
  measured: every term in C correct (except "FVG H1", which no config gets), 19.9 s upload→done on 82.4 s
  (≈ 22.1 s with AI est.), only 1.5 s slower than new b1. Its 120 s estimate is ≈ 30.5 s (RTF scaling) or
  ≈ 29.3 s (straight line), i.e. on the limit. Remaining miss: B's single "FVG" → Cyrillic "ФВГ" (only beam 5
  + condition on gets it, at +60–90 % time).
- new b1 is the fastest but loses most terms late in a note, so extraction would get "іфввг м5 / аж 4 аж 1".
- Beam 5 (any config) fails the time even on the 82 s note (29–36 s, + 2.2 s AI) and only adds B's FVG.
- `old b1` is slower than newcond b1 (RTF 0.24 vs 0.22: full temperature fallback + library-default threads)
  with the same or worse terms.
- Before deciding: re-measure the AI fill with a working key, and ideally record one real 2-min note with
  symbols and QM/BOS/SMT spoken, since none of the three files contains them.

### Odd / notes

1. AI key 401 (above): blocks the live AI part of this AC and the app's "Заповнити з тексту" for Borys.
2. "FVG H1" right after "POI" is never transcribed correctly ("FVH1" in 16 of the 18 runs of C, "FVG-1" in 2).
3. The short note A has a high RTF (0.34 at beam 1, 0.6 at beam 5): fixed per-note cost of a few seconds.
4. Borys's `.env` sets `WHISPER_BEAM_SIZE=5` and `WHISPER_CPU_THREADS=0`, so his running app is in the
   beam 5 rows (29–36 s on 82 s), not on the new defaults. Whatever the PM picks has to be set (or the lines
   removed) in his `.env`.
5. QA DB `trading_journal_qa_m3` kept; it now holds 72 more audio notes on trade 6 (+ a few from two aborted first
   attempts on trade 5; their files were in my scratch dir, so they show `audio_missing` on replay).

## M3-18 Final end-to-end check

Date: 2026-11-05, 16:16–16:18 Brussels. Branch `main` at 67019ac (all M3 code merged). Tester: qa-tester agent.
No product code changed. Acceptance rule: PM M3 decision of 2026-11-05 (docs/DECISIONS.md).

### Method

- Own API (uvicorn, port 8010) + one worker, QA DB `trading_journal_qa_m3`, fixture MT5 source, scratch
  `DATA_DIR`/`LOG_DIR` (outside the repo). Borys's app on 8000/5173 and his real DB untouched.
- Whisper: **code defaults**, no `WHISPER_*` variable set (driver removes any from the child env). Worker INFO
  line of every note: `model small int8, language uk, beam 1, vad on, condition_on_previous_text on,
  temperatures 0,0.4, cpu threads 12`.
- Preflight: `GET /api/health` → `ai.state: "ok"`; trade 6 (GER40, closed, `needs_description`, initial SL set).
- Whisper budget: 1 warm-up note (A, 19 s, discarded, includes the model load: 9.9 s) + 3 rounds × 3 recordings
  = **10 transcriptions, no repeats**. Recording order shuffled per round (seed 20261105).
- Per run: `POST /api/trades/6/audio` → poll `GET /api/audio/{id}` every 0.25 s until `done` (normalized
  transcript) → `POST /api/trades/6/extract` with that transcript. TOTAL = upload→done + extract (both measured).
- Glossary: count from the worker INFO line "Audio note N: K term replacement(s)". To see *which* terms, the
  worker ran through a QA wrapper (`docs/reports/M3-qa-audio/qa_worker_wrap.py`) that records raw vs normalized
  text of each `TranscriptGlossary.apply` call into the scratch dir; the app code itself is unchanged.
  Driver: `docs/reports/M3-qa-audio/final_e2e.py`.
- Thermal (typeperf, ACPI zone): 77–95 °C during the run.
- AI fill: `claude-sonnet-5-5`, no fallback in any run, 0.008–0.012 USD per call.

### Timings (s)

| recording | duration | upload→done (r1/r2/r3) | extract (r1/r2/r3) | TOTAL r1/r2/r3 | TOTAL median | min | max |
|---|---|---|---|---|---|---|---|
| A | 19.0 | 6.4 / 5.6 / 5.6 | 1.2 / 0.9 / 1.0 | 7.6 / 6.5 / 6.6 | **6.6** | 6.5 | 7.6 |
| B | 40.7 | 8.9 / 8.6 / 8.6 | 1.3 / 1.0 / 3.4 | 10.2 / 9.6 / 11.9 | **10.2** | 9.6 | 11.9 |
| C | 82.4 | 13.4 / 13.5 / 13.2 | 2.0 / 2.3 / 2.5 | 15.3 / 15.8 / 15.7 | **15.7** | 15.3 | 15.8 |

Worker transcription time (decode + transcribe): A 4.3–4.4 s, B 7.5–7.7 s, C 12.7–13.0 s (RTF 0.15–0.23).
Faster than M3-13's "newcond b1" (C 18.5 s) because no other config ran before and the model was warm.
The three transcripts of each recording were **identical** in all runs (greedy decode, temperature 0 kept).

### Glossary (per run; same in all 3 runs)

| recording | replacements (worker INFO) | which | correct? |
|---|---|---|---|
| A | 1 | `МТ5` (Cyrillic) → `MT5` | ✅ |
| B | 1 | `ФВГ` → `FVG` | ✅ |
| C | 1 | `FVH1` → `FVG H1` (after "POI") | ✅ (matches the context; the least certain term since M3-13) |

No wrong replacement. In C, H4, H1, IFVG, M5, FTA and Flow came out of Whisper already in Latin (condition on).
Remaining raw-transcript oddities that the glossary does not (and should not) touch: "DAL5" in C (unclear what
was said), misspelled Ukrainian words ("отворилася", "знітя", "Сидап-тайп"); none affected a field.

### Extracted fields (identical in all 3 runs of each recording; `dropped` empty in all 9 runs)

What Borys says (inferred from the normalized transcript, I can't listen to the audio):
- **A**: pre-market filled, waited for the position; changed TP in MT5 after opening; through FTA, RR lower.
- **B**: TP in the terminal on a target (liquidity on the chart); FVG valid because it updates a fractal; also a
  reaction after a liquidity sweep.
- **C**: entry at NY open via POI FVG H1 formed after the Asian-session liquidity was taken in London; reaction
  as FVG; holding to the liquidity of the last consolidation; bias long, trade with the bias; "Сетап H4, H1
  Flow"; entry via IFVG M5; FTA is the target.

| recording | field | extracted (3/3 runs) | spoken? | correct? |
|---|---|---|---|---|
| A | poi_type / fvg_kind / entry_model / timeframes | — | not spoken | ✅ (empty is right) |
| A | everything else | — (fields `{}`) | FTA/RR/TP change spoken, no journal enum value | ✅ plausible; "changed TP after opening" could be a `mistakes` text, left empty (uncertain, not a key field) |
| B | fvg_kind | `fractal_updating` | "FVG валідний через оновлення фракталу" | ✅ (also mentions a reaction after a liquidity sweep; the stated reason is the fractal) |
| B | poi_type | — | "FVG" without a timeframe | ✅ (no H1/H4 said) |
| B | entry_model / timeframes | — | not spoken | ✅ |
| C | poi_type | `fvg_h1` | "POI FVG H1" | ✅ |
| C | fvg_kind | `post_manipulation` | FVG formed after the liquidity sweep | ✅ |
| C | entry_model | `ifvg_m5` | "Заход через IFVG M5" | ✅ |
| C | timeframes | H1 in poi_type, M5 in entry_model | yes | ✅ |
| C | setup_context | — (missing_required) | "Сетап H4, H1 Flow" (timeframes named, no yes/no on synchrony) | ⚠ uncertain: empty is defensible, `yes` would also be a reading |
| C | exit_reason, emotions, followed_plan, quality_rating | — | not spoken | ✅ |

`missing_required`: A = all 9 enum/bool/int fields + chart_links; B = all but fvg_kind; C = setup_context,
exit_reason, followed_plan, emotion_before, emotion_after, quality_rating, chart_links.

Not spoken in any recording (cannot be checked here): QM M5 entry, FVG H4 POI, `na` FVG kind, symbols, QM/BOS/SMT.

### Acceptance (PM 2026-11-05)

| criterion | result |
|---|---|
| 82.4 s note TOTAL (upload + transcription + AI fill) median ≤ 30 s | **pass**: 15.7 s (15.3–15.8) |
| POI type correct in all 3 recordings (where spoken) | **pass**: C `fvg_h1` 3/3; not spoken with a type in A, B |
| Entry model correct (where spoken) | **pass**: C `ifvg_m5` 3/3; not spoken in A, B |
| FVG kind correct (where spoken) | **pass**: B `fractal_updating` 3/3, C `post_manipulation` 3/3; not spoken in A |
| Timeframes correct (where spoken) | **pass**: C H1 (POI) and M5 (entry) 3/3; none spoken in A, B |

**Overall: PASS.**

### Notes

1. No product bug found in this run.
2. QA-setup only: the worker logs `ERROR … Account 1 sync failed: password_missing: MT5_PASSWORD_51234567` against
   the QA DB (the fixture account has no password in `.env`). Visible error as designed; unrelated to voice.
3. `setup_context` in C is the only judgment call (see table); not one of the PM's key fields.
4. QA DB `trading_journal_qa_m3` kept; +10 audio notes on trade 6 (ids 88–97; their files are in my scratch dir,
   so they show `audio_missing` on replay). API and worker stopped.
