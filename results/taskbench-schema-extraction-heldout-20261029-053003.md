# Task benchmark: schema-extraction (20261029-053003)

Fill fixed fields from a short financial document: its kind, currency, and whether a due date is stated. All text is synthetic. Baseline rules were written against the dev split only.

8 items (heldout split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | kind acc | currency acc | due_date acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 1.00 | 1.00 | 1.00 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 1.00 | 0.88 | 0.88 | 0.057 | 0 | 0 | 119.0 | 10442.8 |
| systemone:nimble | 1.00 | 1.00 | 1.00 | 0.029 | 0 | 0 | 157.1 | 9609.3 |
| ollama:qwen3:14b | 1.00 | 0.75 | 1.00 | — | 0 | 0 | 436.0 | 9068.1 |
