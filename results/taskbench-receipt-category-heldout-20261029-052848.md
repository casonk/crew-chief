# Task benchmark: receipt-category (20261029-052848)

Categorize a receipt line and tell whether the charge recurs. All merchants and amounts are synthetic. Baseline rules were written against the dev split only.

8 items (heldout split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | category acc | recurring acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|
| rules | 0.38 | 0.75 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 1.00 | 1.00 | 0.045 | 0 | 0 | 123.8 | 10587.2 |
| systemone:nimble | 1.00 | 1.00 | 0.026 | 0 | 0 | 141.1 | 9816.0 |
| ollama:qwen3:14b | 1.00 | 1.00 | — | 0 | 0 | 331.3 | 8682.8 |
