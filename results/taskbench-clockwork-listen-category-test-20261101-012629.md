# Task benchmark: clockwork-listen-category (20261101-012629)

Sort an item into a Clockwork To Listen category. Names are well-known public works and generic descriptions, not entries from any real list. Baseline rules were written against the dev split only.

10 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 15 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.40 | 0.32 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.40 | 0.32 | 0.785 | 0 | 0 | 0.1 | 0.2 | gated | gated |
| systemone:clef-flash | 1.00 | 1.00 | 0.005 | 0 | 0 | 138.1 | 151.4 | 0.757 | 0.969 |
| systemone:clef | 1.00 | 1.00 | 0.002 | 0 | 0 | 1323.5 | 1344.8 | 0.700 | 0.960 |
| systemone:nimble | 1.00 | 1.00 | 0.004 | 0 | 0 | 156.9 | 185.8 | 0.756 | 0.972 |
| systemone:tev1 | 1.00 | 1.00 | 0.000 | 0 | 0 | 90.4 | 121.8 | 0.805 | 0.980 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 0 | 0 | 0 | 0 | 2 | 0.00 |
| Podcasts | 0 | 0 | 0 | 1 | 1 | 0.00 |
| Audiobooks | 0 | 0 | 1 | 0 | 1 | 0.50 |
| Radio | 0 | 0 | 0 | 1 | 1 | 0.50 |
| Artists | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | — | — | 1.00 | 0.50 | 0.29 |  |

## Confusion matrix: bayes / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 1 | 0 | 0 | 1 | 0 | 0.00 |
| Audiobooks | 1 | 0 | 1 | 0 | 0 | 0.50 |
| Radio | 1 | 0 | 0 | 1 | 0 | 0.50 |
| Artists | 2 | 0 | 0 | 0 | 0 | 0.00 |
| precision | 0.29 | — | 1.00 | 0.50 | — |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Albums | Podcasts | Audiobooks | Radio | Artists | recall |
|---|---|---|---|---|---|---|
| Albums | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Podcasts | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Audiobooks | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Radio | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Artists | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |
