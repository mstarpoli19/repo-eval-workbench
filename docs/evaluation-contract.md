# Evaluation contract

## Dataset record

One UTF-8 JSON object per line:

```json
{"id":"mutable-example","path":"sample.py","source":"def add(x, items=[]):\n    return items + [x]\n","expected":[{"rule_id":"mutable-default","line":1}],"explanation":"A mutable list default is shared between calls."}
```

Dataset fields are exactly `id`, `path`, `source`, `expected`, and `explanation`. `expected` contains target findings, not a general assertion that every target pattern is a vulnerability. Paths are logical source identifiers; the evaluator never opens them or executes `source`.

## Prediction record

```json
{"id":"mutable-example","findings":[{"rule_id":"mutable-default","line":1}]}
```

Fields are exactly `id` and `findings`. Findings have exactly `rule_id` and `line`. The four rule IDs are listed in the root README. Lines are positive, one-based integers pointing into the corresponding task source. JSON booleans are not accepted as integers.

An explicit `"findings": []` means "reviewed; no target findings." An omitted task means "no review supplied." They are intentionally different.

Unknown task IDs, extra fields, duplicate IDs or findings, duplicate JSON keys, non-finite values, unsupported rules, invalid line numbers, and oversized inputs fail validation. This is a deliberately strict wire contract, not a natural-language grader. Empty datasets are rejected.

## Matching and partial credit

Within one task, a finding matches only if **both rule ID and line number match**. Each finding can match once.

- TP: predicted findings in the expected set.
- FP: predicted findings outside the expected set.
- FN: expected findings absent from the prediction.
- Supplied task score: `2TP / (2TP + FP + FN)`.
- Supplied clean task with no predicted findings: **1**.
- Missing prediction: **0**, including a missing clean task.
- Overall score: mean of task scores, all tasks weighted equally.

Example: a task with two target findings receives one correct finding and one invented finding. TP=1, FP=1, FN=1; precision=0.5, recall=0.5, and task F1=0.5. Simply listing every possible rule is penalized through false positives.

## Additional metrics

Micro precision, recall, and F1 pool finding counts across all tasks. Missing reviews contribute their expected findings as false negatives. For pooled counts with no expected and no predicted findings, all three metrics are 1; when only one set is empty, the undefined precision or recall is reported as 0. `task_coverage` is supplied task count divided by dataset task count.

A dataset containing only clean tasks can therefore have perfect pooled finding metrics even when some reviews are missing. The macro task score and coverage expose that omission. Do not use micro F1 alone as a completion score.

## Limits

The implementation defines explicit limits for files, records, source size, and findings. These are input-validation bounds, not protection against a hostile OS or arbitrary resource-exhaustion attacks. Use trusted, local input files in a stable checkout. See module constants for the exact current limits.
