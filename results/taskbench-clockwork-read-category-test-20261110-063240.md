# Task benchmark: clockwork-read-category (20261110-063240)

Sort an item into a Clockwork To Read category. Titles are generic or well-known public works, not entries from any real list. Baseline rules were written against the dev split only.

30 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 12 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.27 | 0.11 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.53 | 0.54 | 0.533 | 0 | 0 | 0.1 | 0.1 | gated | gated |
| systemone:clef-flash | 1.00 | 1.00 | 0.003 | 0 | 0 | 121.1 | 140.5 | 0.787 | 0.977 |
| systemone:clef | 1.00 | 1.00 | 0.001 | 0 | 0 | 725.6 | 738.3 | 0.706 | 0.967 |
| systemone:nimble | 1.00 | 1.00 | 0.002 | 0 | 0 | 130.1 | 131.9 | 0.796 | 0.978 |
| systemone:tev1 | 1.00 | 1.00 | 0.019 | 0 | 0 | 75.8 | 94.8 | 0.840 | 0.980 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 8 | 0 | 0 | 0 | 1.00 |
| Articles | 8 | 0 | 0 | 0 | 0.00 |
| Papers | 7 | 0 | 0 | 0 | 0.00 |
| Comics | 7 | 0 | 0 | 0 | 0.00 |
| precision | 0.27 | — | — | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 5 | 3 | 0 | 0 | 0.62 |
| Articles | 2 | 6 | 0 | 0 | 0.75 |
| Papers | 4 | 1 | 2 | 0 | 0.29 |
| Comics | 4 | 0 | 0 | 3 | 0.43 |
| precision | 0.33 | 0.60 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 8 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 8 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 7 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 8 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 8 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 7 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 8 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 8 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 7 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Books | Articles | Papers | Comics | recall |
|---|---|---|---|---|---|
| Books | 8 | 0 | 0 | 0 | 1.00 |
| Articles | 0 | 8 | 0 | 0 | 1.00 |
| Papers | 0 | 0 | 7 | 0 | 1.00 |
| Comics | 0 | 0 | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |
