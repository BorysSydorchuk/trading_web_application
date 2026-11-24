# Whisper model memory in the worker (report, no code)

Question (owner/PM 2026-11-24): does the worker keep the Whisper model loaded permanently?

## Answer: yes, after the first voice note

- `app/services/transcriber.py` keeps loaded models in a module dict `_models` (key: model, compute type,
  threads). Nothing ever removes an entry.
- `app/worker/main.py` creates one `WhisperTranscriber` per worker process. The model loads on the first
  note (lazy), then stays in memory until the worker stops. This was a deliberate M3 choice
  (DECISIONS 2026-11-04: "The model stays loaded in the worker").
- The API process never imports faster-whisper.
- Measured 2026-11-24 14:17: the worker was 147 MB, because no note had been transcribed since the start.
  So the model is not the cause of the low free RAM at that moment (see `ctrader-phase-b.md`).

## Proposal (PM APPROVED 2026-11-24, tier S, built on `fix/whisper-idle-unload`)

Tier S, about 2 files (`transcriber.py`, `worker/main.py`) plus tests with a fake model:

1. Keep the lazy load on the first note (no change).
2. Remember the time of the last finished note. A small worker job (every minute) drops the model after
   `WHISPER_IDLE_UNLOAD_MINUTES` idle minutes (default 15; 0 = never unload). It removes the entry from
   `_models` under the existing lock, then runs `gc.collect()`. It never unloads while a note is
   being transcribed.
3. One log line on load and one on unload, with the idle minutes.

## Expected effect

- Saving: the resident size of `small` int8 on CPU, estimated at about 0.5-1 GB. This is not measured yet.
  I would measure it once on the next normal voice note (worker working set before and after), with no
  extra Whisper runs.
- Cost: the first note after an idle period loads the model again. A cached load took about 1.4 s on this
  laptop (STATUS M3). Each load also sends HEAD requests to huggingface.co (M3-qa). This stays within the
  30 s target.
- Risk: on Windows the allocator may not return all freed memory to the OS at once. The measurement will
  show the real saving.
- Note: the gate itself does not load Whisper (the real-model test is skipped), so this change does not
  help the gate RAM check directly. It helps when Borys records notes and then runs heavy work later.

## Built (2026-11-24)

- `WHISPER_IDLE_UNLOAD_S = 15 * 60` in `transcriber.py` (constant, no new `.env` key). The idle time counts
  from the end of the last note. The check runs inside the transcription job after every cycle, so a
  note in progress is never cut off. code-reviewer APPROVE (LOW about the start/end of the timer fixed).

## Measured (2026-11-24 14:42, app stopped, model `small` int8, 12 threads, load only, no transcription)

One measuring run in a separate Python process with the real `WhisperTranscriber`, memory from
`GetProcessMemoryInfo` (an earlier run of the same script printed 0 MB because of a ctypes handle type,
so the model was loaded twice in that run too; no audio was transcribed):

| State | Working set (RAM) | Private (commit) |
|---|---|---|
| Before load | 59 MB | 45 MB |
| Model loaded (first load 1.17 s) | 408 MB | 2764 MB |
| After unload (and 2 s later) | 102 MB | 571 MB |
| Reloaded (0.93 s) | 409 MB | 2765 MB |

- Real saving: about **306 MB of RAM** (working set) and about **2.2 GB of commit charge** per unload.
  The 43 MB working set and 526 MB commit left after the unload are the faster-whisper/CTranslate2
  libraries, which stay imported.
- Reload time: **0.93 s** (cached model). The first note after 15 idle minutes waits about 1 s longer.
- During a transcription the working set is larger than the load-only figure; this was not measured, to
  avoid an extra Whisper run.
