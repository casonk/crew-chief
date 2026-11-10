# Task benchmark: clockwork-listen-category (20261110-063401)

Sort an item into a Clockwork To Listen category. Names are well-known public works and generic descriptions, not entries from any real list. Baseline rules were written against the dev split only.

30 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 15 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.70 | 0.71 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.63 | 0.59 | 0.458 | 0 | 0 | 0.1 | 0.1 | gated | gated |
| systemone:clef-flash | 1.00 | 1.00 | 0.003 | 0 | 0 | 133.3 | 136.1 | 0.784 | 0.976 |
| systemone:clef | 1.00 | 1.00 | 0.001 | 0 | 0 | 762.9 | 771.0 | 0.705 | 0.966 |
| systemone:nimble | 1.00 | 1.00 | 0.001 | 0 | 0 | 151.3 | 156.5 | 0.792 | 0.978 |
| systemone:tev1 | 0.97 | 0.97 | 0.026 | 0 | 0 | 83.0 | 86.1 | 0.814 | 0.948 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 2 | 0 | 0 | 0 | 4 | 0.33 |
| Podcasts | 0 | 4 | 0 | 1 | 1 | 0.67 |
| Audiobooks | 0 | 0 | 5 | 0 | 1 | 0.83 |
| Radio | 0 | 0 | 0 | 4 | 2 | 0.67 |
| Artists | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 0.80 | 0.43 |  |

## Confusion matrix: bayes / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 5 | 0 | 1 | 0 | 0 | 0.83 |
| Podcasts | 1 | 4 | 0 | 1 | 0 | 0.67 |
| Audiobooks | 1 | 0 | 5 | 0 | 0 | 0.83 |
| Radio | 1 | 0 | 0 | 5 | 0 | 0.83 |
| Artists | 6 | 0 | 0 | 0 | 0 | 0.00 |
| precision | 0.36 | 1.00 | 0.83 | 0.83 | — |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Artists | 1 | 0 | 0 | 0 | 5 | 0.83 |
| precision | 0.86 | 1.00 | 1.00 | 1.00 | 1.00 |  |
