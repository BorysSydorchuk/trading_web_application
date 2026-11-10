# config/

Editable YAML configuration (not secrets):
- `rules.yaml`: session boundaries and trading rules (PRD 6.3, 6.9), added in M1.
- `journal_fields.yaml`: journal field definitions (PRD 6.4), added in M1.
- `ai_pricing.yaml`: Anthropic prices per million tokens per model (cost in `logs/ai_usage.jsonl`), added in M2.
- `extraction.yaml`: number words the AI extraction accepts for number fields ("четвірка" = 4); add your own words or phrases, added in M3.
- `transcription.yaml`: glossary of trading terms passed to Whisper as a hint for voice notes, added in M3.
- `bias.yaml`: bias symbols with their spoken aliases and the dashboard reminder windows, added in M4. Its symbols must be names from `symbols.yaml`.
- `symbols.yaml`: the canonical symbol names the app uses everywhere (journal, analytics, bias, rules, calculator) and the broker names behind them, optionally per firm (FundedNext calls the DAX `GER30`, the app shows `GER40`); MT5 calls always use the broker's name. The worker syncs the specs of these symbols for every account and renames stored trades when the file changes (next sync). Replaces `rules.yaml` `sync.watch_symbols` (that key is now an error). Added in M5-08.
