# Task benchmark: receipt-category (20261029-052815)

Categorize a receipt line and tell whether the charge recurs. All merchants and amounts are synthetic. Baseline rules were written against the dev split only.

16 items (dev split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | category acc | recurring acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|
| rules | 1.00 | 1.00 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 0.94 | 1.00 | 0.037 | 0 | 0 | 104.3 | 124.6 |
| systemone:nimble | 0.94 | 1.00 | 0.021 | 0 | 0 | 138.9 | 146.4 |
| ollama:qwen3:14b | 0.94 | 0.94 | — | 0 | 0 | 338.4 | 363.6 |
