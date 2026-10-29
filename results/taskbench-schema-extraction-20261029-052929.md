# Task benchmark: schema-extraction (20261029-052929)

Fill fixed fields from a short financial document: its kind, currency, and whether a due date is stated. All text is synthetic. Baseline rules were written against the dev split only.

16 items (dev split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | kind acc | currency acc | due_date acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 0.88 | 1.00 | 1.00 | — | 0 | 0 | 0.0 | 0.1 |
| systemone:clef-flash | 0.94 | 0.94 | 1.00 | 0.070 | 0 | 0 | 119.6 | 127.2 |
| systemone:nimble | 0.94 | 0.94 | 1.00 | 0.078 | 0 | 0 | 157.9 | 180.4 |
| ollama:qwen3:14b | 1.00 | 1.00 | 1.00 | — | 0 | 0 | 437.2 | 459.1 |
