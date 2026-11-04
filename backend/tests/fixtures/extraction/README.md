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
  "expected_missing_required": ["..."]
}
```

- `model_output`: the model's JSON answer (recorded from a real run, or hand-written to
  simulate a bad answer). Must be an object; each entry `{value, evidence}` or `null`.
- `expected_fields`: exactly the `fields` of the result (keys and values), after guards.
- `expected_dropped` (optional, default `[]`): the `dropped` list, in YAML key order.
- `expected_missing_required` (optional): if present, compared exactly.

Invariants checked for every fixture, whatever `expected_*` says:
- every kept value has evidence (>= 3 chars, whole words) that appears in `text`;
- every kept free-text value is itself a whole-word piece of `text` (his own words);
- no kept text value contains `?` unless its evidence does (no questions);
- no key outside the schema (`rule_violations`, `bias_alignment`, `chart_links`, …) is kept.

Reasons: `evidence_not_in_text`, `invalid_option`, `out_of_range`, `parent_not_other`,
`question`, `not_fillable`.
