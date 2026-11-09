# Bias extraction fixtures (M4-06)

One JSON file per sample bias note. `tests/services/test_bias_extraction_fixtures.py` loads
every `*.json` here and runs the full bias extraction (prompt, schema, guards, usage log)
with a fake model that replays `model_output`. It never calls the real API.

```json
{
  "description": "what this sample covers (language mix, aliases, traps)",
  "kind": "pre_london | pre_ny | weekly | monthly",
  "text": "the bias note exactly as Borys would type/say it",
  "model_output": [ { "symbol": "XAUUSD", "key": "direction", "value": "bullish",
                      "evidence": "verbatim quote" } ],
  "expected_entries": { "XAUUSD": { "direction": "bullish", "confidence": 2 } },
  "expected_dropped": [ { "symbol": "GER40", "key": "direction", "reason": "symbol_not_in_text" } ],
  "eval_expected_entries": { "XAUUSD": { "direction": "bullish" } }
}
```

- `model_output`: the model's `entries` list in the wire format (`value` is always a
  string, e.g. `"2"` for a confidence); recorded from a real run or hand-written to simulate
  a bad answer.
- `expected_entries`: exactly the result per symbol after the guards (symbols with no kept
  value are absent; the result order is bias.yaml order, checked by the test).
- `expected_dropped` (optional, default `[]`): the `dropped` list, sorted by bias.yaml symbol
  order, then field order (direction, key_levels, narrative, confidence).
- `eval_expected_entries` (optional, for a future live eval): the right answer for `text`
  when it differs from `expected_entries`. Not used by the offline test.

Invariants checked for every fixture: every kept value has evidence that appears in `text`
(>= 3 letters/digits, whole words); its symbol is named in `text` (symbol name or a
bias.yaml alias); kept free text is a whole-word piece of `text` (`key_levels`: each of its
"; "-joined pieces is); no kept text contains `?` unless its evidence does.

`key_levels` may name several levels joined by "; " (PM 2026-11-09): every piece must be a
whole-word piece of `text`, the pieces must occur in `text` in that order and must not
repeat (else `invalid_option`). `narrative` stays one continuous piece.

Reasons: `evidence_not_in_text`, `invalid_option`, `out_of_range`, `question`,
`not_fillable`, `symbol_not_in_text`.
