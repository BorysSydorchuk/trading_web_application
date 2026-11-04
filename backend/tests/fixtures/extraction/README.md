# Extraction fixtures (M2-04 format, QA fills in M2-07)

One JSON file per sample trade description. `tests/services/test_extraction_fixtures.py`
loads every `*.json` here and runs the full extraction (prompt, schema, guards, usage log)
with a fake model that replays `model_output`. It never calls the real API.

```json
{
  "description": "what this sample covers (language mix, terms, traps)",
  "text": "the trade description exactly as Borys would type/say it",
  "model_output": { "<key>": { "value": "...", "evidence": "verbatim quote" } },
  "expected_fields": { "<key>": "<value after the guards>" },
  "expected_dropped": [ { "key": "<key>", "reason": "<guard reason>" } ],
  "expected_missing_required": ["..."],
  "eval_expected_fields": { "<key>": "<right answer for the text>" }
}
```

- `model_output`: the model's JSON answer (recorded from a real run, or hand-written to
  simulate a bad answer), written per key: an object, each entry `{value, evidence}` or
  `null` (values typed: strings, numbers, true/false, lists for multi-choice). The fake
  model sends it in the real wire format `{"fields": [{"key", "value", "evidence"}]}`
  (`tests/services/ai_fakes.py` `to_wire`), so the conversion is tested too.
- `expected_fields`: exactly the `fields` of the result (keys and values), after guards.
- `expected_dropped` (optional, default `[]`): the `dropped` list, in YAML key order.
- `expected_missing_required` (optional): if present, compared exactly.
- `eval_expected_fields` (optional, live eval only): the right answer for `text`, when it
  differs from `expected_fields` (a deliberately bad `model_output` loses values a correct
  model should keep). Default: `expected_fields`. Not used by the offline test.

Invariants checked for every fixture, whatever `expected_*` says:
- every kept value has evidence (>= 3 letters/digits, whole words) that appears in `text`;
- every kept free-text value is itself a whole-word piece of `text` (his own words);
- no kept text value contains `?` unless its evidence does (no questions);
- no key outside the schema (`rule_violations`, `bias_alignment`, `chart_links`, …) is kept.

Reasons: `evidence_not_in_text`, `invalid_option`, `out_of_range`, `parent_not_other`,
`question`, `not_fillable`.

## Live eval (real API, costs money)

`make ai-eval` (or `make ai-eval AI_MODEL=claude-opus-5-5 AI_EFFORT=medium`) sends every
`text` here through the real extraction service (`app/tools/ai_eval.py`) and compares the
result with `eval_expected_fields` (else `expected_fields`); `model_output` is ignored.
Prints duration, tokens, cost, filled and dropped fields per fixture, then totals: mean/p95
duration for all calls (failed ones included) and for successful calls, the cost of all
attempts (failed ones included) and field accuracy of the successful calls. Needs
`ANTHROPIC_API_KEY` (exit 1 without it); usage lines go to `logs/ai_usage.jsonl` with
purpose `eval`.
