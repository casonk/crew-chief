# Task benchmark: clockwork-todo-category (20261101-012935)

Sort a to-do entry into a Clockwork Todo category. Entries are synthetic. Baseline rules were written against the dev split only.

10 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 15 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.30 | 0.21 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.40 | 0.32 | 0.811 | 0 | 0 | 0.3 | 0.4 | gated | gated |
| systemone:clef-flash | 1.00 | 1.00 | 0.040 | 0 | 0 | 143.4 | 147.5 | 0.761 | 0.971 |
| systemone:clef | 1.00 | 1.00 | 0.024 | 0 | 0 | 1402.4 | 1414.4 | 0.700 | 0.960 |
| systemone:nimble | 1.00 | 1.00 | 0.002 | 0 | 0 | 162.7 | 179.4 | 0.759 | 0.972 |
| systemone:tev1 | 1.00 | 1.00 | 0.027 | 0 | 0 | 87.2 | 90.3 | 0.819 | 0.980 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 2 | 0 | 0 | 0 | 0 | 0.00 |
| Errands | 1 | 0 | 1 | 0 | 0 | 0.50 |
| Goals | 2 | 0 | 0 | 0 | 0 | 0.00 |
| Hardware | 2 | 0 | 0 | 0 | 0 | 0.00 |
| precision | 0.22 | — | 1.00 | — | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 2 | 0 | 0 | 0 | 0 | 0.00 |
| Errands | 1 | 0 | 1 | 0 | 0 | 0.50 |
| Goals | 1 | 0 | 0 | 0 | 1 | 0.00 |
| Hardware | 1 | 0 | 0 | 0 | 1 | 0.50 |
| precision | 0.29 | — | 1.00 | — | 0.50 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Tasks | Projects | Errands | Goals | Hardware | recall |
|---|---|---|---|---|---|---|
| Tasks | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Projects | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Errands | 0 | 0 | 2 | 0 | 0 | 1.00 |
| Goals | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Hardware | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |
