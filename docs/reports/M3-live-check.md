# M3 live check (Borys)

Run items 1–8 now (no microphone needed). Items 9–12 need a live microphone; run them later.
Mark each item ✅ / ❌ and add a short note if something differs. Wait until QA (M3-13) has finished, because it uses the same QA database and ports.

**Start against the QA database** (in the repo root; your real journal is not touched; the script copies `config/` to `%TEMP%\tj-qa\config` and makes `lesson` required only there, then starts the app like `start.bat`):
```powershell
python scripts\qa_live_check.py
```
Optional: `--whisper-condition-on-previous-text`, `--no-browser`. Do not edit the config copy with PowerShell 5.1 `Get-Content`/`Set-Content`: they re-encode UTF-8 and garble the Ukrainian labels (M3-15).
Stop with Ctrl+C or `stop.bat`.

| # | Mic | Do | Expected |
|---|---|---|---|
| 1 | – | Run the start block above | Browser opens, status bar green, Журнал lists the QA fixture trades (not your real ones) |
| 2 | – | Open a closed trade → "Описати" → "Завантажити аудіо" → pick an .ogg from `data/qa-voice` | Upload, then a progress bar, then the transcript appears in the text box; the note can be replayed |
| 3 | – | Edit a word in the transcript → "Заповнити з тексту" → "Зберегти чернетку" | Fields prefilled (AI markers), your edit kept in the text, draft saved |
| 4 | – | "Завантажити аудіо" with a non-audio file (e.g. a .pdf or .txt) | Ukrainian "Непідтримуваний формат аудіо…" message, nothing uploaded |
| 5 | – | Open a trade with an older QA note (its file is gone) | Note shows failed with "Аудіофайл зник з диска…" and "Спробувати ще раз"; retry → pending → failed again with the same message |
| 6 | – | DevTools (F12) → Network → Offline → "Завантажити аудіо" with an .ogg → back Online → "Завантажити ще раз" | Upload error shown, recording kept with replay + "Завантажити ще раз" / "Видалити запис"; after Online the retry uploads and transcribes |
| 7 | – | Журнал → tick "Неповні за новими полями" | Only closed trades without "Урок" are listed; untick → all trades again; the filter survives F5 |
| 8 | – | Open one of those trades → "Описати" | Grey (not red) note "Нові поля, які ще не заповнені: Урок"; "Урок" not red, "Зберегти" (complete) works; typing a lesson removes it from the note |
| 9 | 🎤 | Hold "Утримуйте й говоріть" for ~20 s, release | Upload, progress, transcript appended to the text box automatically |
| 10 | 🎤 | Tap the button for less than 1 s | "Запис коротший за 1 с, його не збережено…", nothing uploaded |
| 11 | 🎤 | Browser site settings → block microphone → hold the button | "Немає доступу до мікрофона. Дозвольте мікрофон…" message; text box and "Завантажити аудіо" still work |
| 12 | 🎤 | Record a ~2 min description of a real trade, then "Заповнити з тексту" | Transcript + fields prefilled in ≤ 30 s from release; trading terms (FVG, IFVG, QM, POI, BOS, SMT, symbols) correct |
