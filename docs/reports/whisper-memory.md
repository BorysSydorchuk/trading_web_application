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

## Proposal (waits for PM approval)

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
