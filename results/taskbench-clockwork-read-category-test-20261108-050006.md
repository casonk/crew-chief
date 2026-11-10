# Task benchmark: clockwork-read-category (20261108-050006)

Sort an item into a Clockwork To Read category. Titles are generic or well-known public works, not entries from any real list. Baseline rules were written against the dev split only.

8 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 12 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.25 | 0.10 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.50 | 0.45 | 0.711 | 0 | 0 | 0.1 | 0.3 | gated | gated |
| systemone:clef | 1.00 | 1.00 | 0.002 | 0 | 0 | 738.7 | 18560.3 | gated | 0.960 |
| systemone:clef-flash | 1.00 | 1.00 | 0.009 | 0 | 0 | 129.2 | 10355.1 | gated | 0.968 |
| systemone:nimble | 1.00 | 1.00 | 0.001 | 0 | 0 | 134.6 | 9604.6 | gated | 0.969 |
| systemone:tev1 | 1.00 | 1.00 | 0.021 | 0 | 0 | 76.4 | 3563.3 | gated | 0.979 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 2 | 0 | 0 | 0 | 1.00 |
| Articles | 2 | 0 | 0 | 0 | 0.00 |
| Papers | 2 | 0 | 0 | 0 | 0.00 |
| Comics | 2 | 0 | 0 | 0 | 0.00 |
| precision | 0.25 | — | — | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 1 | 1 | 0 | 0 | 0.50 |
| Articles | 0 | 2 | 0 | 0 | 1.00 |
| Papers | 2 | 0 | 0 | 0 | 0.00 |
| Comics | 1 | 0 | 0 | 1 | 0.50 |
| precision | 0.25 | 0.67 | — | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 2 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 2 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 2 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 2 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 2 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 2 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 2 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 2 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 2 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 2 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 2 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 2 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |
