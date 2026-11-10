# Task benchmark: clockwork-watch-category (20261110-063122)

Sort a title into a Clockwork To Watch category. Titles are well-known public works, not entries from any real list. Baseline rules were written against the dev split only.

30 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 12 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.27 | 0.11 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.27 | 0.11 | 0.726 | 0 | 0 | 0.1 | 0.1 | gated | gated |
| systemone:clef-flash | 0.93 | 0.93 | 0.083 | 0 | 0 | 117.5 | 137.2 | 0.734 | 0.912 |
| systemone:clef | 1.00 | 1.00 | 0.016 | 0 | 0 | 717.9 | 726.3 | 0.706 | 0.967 |
| systemone:nimble | 1.00 | 1.00 | 0.018 | 0 | 0 | 120.2 | 137.6 | 0.801 | 0.978 |
| systemone:tev1 | 0.87 | 0.84 | 0.147 | 0 | 0 | 71.9 | 85.3 | 0.760 | 0.854 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Movies | TV Shows | Anime | Documentaries | recall |
|---|---|---|---|---|---|
| Movies | 8 | 0 | 0 | 0 | 1.00 |
| TV Shows | 8 | 0 | 0 | 0 | 0.00 |
| Anime | 7 | 0 | 0 | 0 | 0.00 |
| Documentaries | 7 | 0 | 0 | 0 | 0.00 |
| precision | 0.27 | — | — | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Movies | TV Shows | Anime | Documentaries | recall |
|---|---|---|---|---|---|
| Movies | 8 | 0 | 0 | 0 | 1.00 |
| TV Shows | 8 | 0 | 0 | 0 | 0.00 |
| Anime | 7 | 0 | 0 | 0 | 0.00 |
| Documentaries | 7 | 0 | 0 | 0 | 0.00 |
| precision | 0.27 | — | — | — |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Movies | TV Shows | Anime | Documentaries | recall |
|---|---|---|---|---|---|
| Movies | 8 | 0 | 0 | 0 | 1.00 |
| TV Shows | 0 | 7 | 1 | 0 | 0.88 |
| Anime | 0 | 0 | 7 | 0 | 1.00 |
| Documentaries | 1 | 0 | 0 | 6 | 0.86 |
| precision | 0.89 | 1.00 | 0.88 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Movies | TV Shows | Anime | Documentaries | recall |
|---|---|---|---|---|---|
| Movies | 8 | 0 | 0 | 0 | 1.00 |
| TV Shows | 0 | 8 | 0 | 0 | 1.00 |
| Anime | 0 | 0 | 7 | 0 | 1.00 |
| Documentaries | 0 | 0 | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Movies | TV Shows | Anime | Documentaries | recall |
|---|---|---|---|---|---|
| Movies | 8 | 0 | 0 | 0 | 1.00 |
| TV Shows | 0 | 8 | 0 | 0 | 1.00 |
| Anime | 0 | 0 | 7 | 0 | 1.00 |
| Documentaries | 0 | 0 | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Movies | TV Shows | Anime | Documentaries | recall |
|---|---|---|---|---|---|
| Movies | 8 | 0 | 0 | 0 | 1.00 |
| TV Shows | 0 | 8 | 0 | 0 | 1.00 |
| Anime | 0 | 0 | 7 | 0 | 1.00 |
| Documentaries | 2 | 2 | 0 | 3 | 0.43 |
| precision | 0.80 | 0.80 | 1.00 | 1.00 |  |
