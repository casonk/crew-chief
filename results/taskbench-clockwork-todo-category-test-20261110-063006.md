# Task benchmark: clockwork-todo-category (20261110-063006)

Sort a to-do entry into a Clockwork Todo category. Entries are synthetic. Baseline rules were written against the dev split only.

30 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 15 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.27 | 0.17 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.43 | 0.43 | 0.699 | 0 | 0 | 0.1 | 0.1 | gated | gated |
| systemone:clef-flash | 1.00 | 1.00 | 0.034 | 0 | 0 | 134.9 | 140.7 | 0.780 | 0.976 |
| systemone:clef | 1.00 | 1.00 | 0.016 | 0 | 0 | 816.8 | 824.7 | 0.704 | 0.962 |
| systemone:nimble | 1.00 | 1.00 | 0.010 | 0 | 0 | 154.8 | 159.0 | 0.770 | 0.975 |
| systemone:tev1 | 1.00 | 1.00 | 0.044 | 0 | 0 | 83.5 | 86.3 | 0.819 | 0.980 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 6 | 0 | 0 | 0 | 0 | 0.00 |
| Errands | 4 | 0 | 2 | 0 | 0 | 0.33 |
| Goals | 6 | 0 | 0 | 0 | 0 | 0.00 |
| Hardware | 6 | 0 | 0 | 0 | 0 | 0.00 |
| precision | 0.21 | — | 1.00 | — | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 5 | 1 | 0 | 0 | 0 | 0.17 |
| Errands | 3 | 1 | 2 | 0 | 0 | 0.33 |
| Goals | 2 | 1 | 0 | 2 | 1 | 0.33 |
| Hardware | 4 | 0 | 0 | 0 | 2 | 0.33 |
| precision | 0.30 | 0.33 | 1.00 | 1.00 | 0.67 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 6 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 6 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 6 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 6 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |
