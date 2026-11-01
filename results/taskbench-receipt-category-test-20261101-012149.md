# Task benchmark: receipt-category (20261101-012149)

Categorize a receipt line and tell whether the charge recurs. All merchants and amounts are synthetic. Baseline rules were written against the dev split only.

8 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 16 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | recurring acc | category macro F1 | recurring macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 0.38 | 0.75 | 0.24 | 0.43 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.25 | 0.88 | 0.19 | 0.80 | 0.635 | 0 | 0 | 0.5 | 0.9 | gated | gated |
| systemone:clef-flash | 1.00 | 1.00 | 1.00 | 1.00 | 0.008 | 0 | 0 | 223.4 | 11470.9 | gated | 0.966 |
| systemone:clef | 1.00 | 1.00 | 1.00 | 1.00 | 0.001 | 0 | 0 | 1625.1 | 17722.5 | gated | 0.958 |
| systemone:nimble | 1.00 | 1.00 | 1.00 | 1.00 | 0.002 | 0 | 0 | 278.5 | 8520.7 | gated | 0.970 |
| systemone:tev1 | 1.00 | 1.00 | 1.00 | 1.00 | 0.009 | 0 | 0 | 165.3 | 4180.4 | gated | 0.977 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | groceries | dining | transport | utilities | entertainment | health | recall |
|---|---|---|---|---|---|---|---|
| groceries | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| dining | 1 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| transport | 1 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| utilities | 1 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| entertainment | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| health | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 |
| precision | 0.29 | — | — | — | — | 1.00 |  |

## Confusion matrix: rules / recurring

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 0 | 2 | 0.00 |
| false | 0 | 6 | 1.00 |
| precision | — | 0.75 |  |

## Confusion matrix: bayes / category

| expected \ answered | groceries | dining | transport | utilities | entertainment | health | recall |
|---|---|---|---|---|---|---|---|
| groceries | 0 | 2 | 0 | 0 | 0 | 0 | 0.00 |
| dining | 0 | 0 | 0 | 0 | 0 | 1 | 0.00 |
| transport | 0 | 1 | 0 | 0 | 0 | 0 | 0.00 |
| utilities | 0 | 0 | 1 | 0 | 0 | 0 | 0.00 |
| entertainment | 0 | 0 | 0 | 0 | 1 | 1 | 0.50 |
| health | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 |
| precision | — | 0.00 | 0.00 | — | 1.00 | 0.33 |  |

## Confusion matrix: bayes / recurring

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 1 | 1 | 0.50 |
| false | 0 | 6 | 1.00 |
| precision | 1.00 | 0.86 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | groceries | dining | transport | utilities | entertainment | health | recall |
|---|---|---|---|---|---|---|---|
| groceries | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| dining | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 |
| transport | 0 | 0 | 1 | 0 | 0 | 0 | 1.00 |
| utilities | 0 | 0 | 0 | 1 | 0 | 0 | 1.00 |
| entertainment | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / recurring

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | groceries | dining | transport | utilities | entertainment | health | recall |
|---|---|---|---|---|---|---|---|
| groceries | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| dining | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 |
| transport | 0 | 0 | 1 | 0 | 0 | 0 | 1.00 |
| utilities | 0 | 0 | 0 | 1 | 0 | 0 | 1.00 |
| entertainment | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / recurring

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | groceries | dining | transport | utilities | entertainment | health | recall |
|---|---|---|---|---|---|---|---|
| groceries | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| dining | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 |
| transport | 0 | 0 | 1 | 0 | 0 | 0 | 1.00 |
| utilities | 0 | 0 | 0 | 1 | 0 | 0 | 1.00 |
| entertainment | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / recurring

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | groceries | dining | transport | utilities | entertainment | health | recall |
|---|---|---|---|---|---|---|---|
| groceries | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| dining | 0 | 1 | 0 | 0 | 0 | 0 | 1.00 |
| transport | 0 | 0 | 1 | 0 | 0 | 0 | 1.00 |
| utilities | 0 | 0 | 0 | 1 | 0 | 0 | 1.00 |
| entertainment | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / recurring

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 6 | 1.00 |
| precision | 1.00 | 1.00 |  |
