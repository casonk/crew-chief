# Task benchmark: mail-triage (20261101-052306)

Triage an incoming email: its kind, how much attention it needs, and whether it looks like phishing. All messages are synthetic. Baseline rules were written against the dev split only.

8 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 16 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | action acc | phishing acc | category macro F1 | action macro F1 | phishing macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 0.62 | 0.50 | 0.75 | 0.51 | 0.43 | 0.43 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.62 | 0.50 | 1.00 | 0.53 | 0.40 | 1.00 | 0.455 | 0 | 0 | 1.0 | 1.1 | gated | gated |
| systemone:clef | 1.00 | 0.88 | 1.00 | 1.00 | 0.84 | 1.00 | 0.074 | 0 | 0 | 1382.7 | 18684.0 | gated | 0.919 |
| systemone:clef-flash | 1.00 | 0.88 | 0.88 | 1.00 | 0.84 | 0.80 | 0.099 | 0 | 0 | 314.7 | 10961.4 | gated | 0.888 |
| systemone:nimble | 1.00 | 0.50 | 1.00 | 1.00 | 0.39 | 1.00 | 0.296 | 0 | 0 | 399.0 | 9804.0 | gated | gated |
| systemone:tev1 | 1.00 | 0.50 | 1.00 | 1.00 | 0.37 | 1.00 | 0.256 | 0 | 0 | 247.0 | 3623.2 | gated | gated |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | personal | billing | work | promo | security | recall |
|---|---|---|---|---|---|---|
| personal | 2 | 0 | 0 | 0 | 0 | 1.00 |
| billing | 0 | 1 | 0 | 0 | 0 | 1.00 |
| work | 2 | 0 | 0 | 0 | 0 | 0.00 |
| promo | 1 | 0 | 0 | 0 | 0 | 0.00 |
| security | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 0.40 | 1.00 | — | — | 1.00 |  |

## Confusion matrix: rules / action

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 0 | 3 | 0 | 0.00 |
| 1 | 0 | 2 | 0 | 1.00 |
| 2 | 0 | 1 | 2 | 0.67 |
| precision | — | 0.33 | 1.00 |  |

## Confusion matrix: rules / phishing

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 0 | 1 | 0.00 |
| false | 1 | 6 | 0.86 |
| precision | 0.00 | 0.86 |  |

## Confusion matrix: bayes / category

| expected \ answered | personal | billing | work | promo | security | recall |
|---|---|---|---|---|---|---|
| personal | 0 | 0 | 2 | 0 | 0 | 0.00 |
| billing | 0 | 1 | 0 | 0 | 0 | 1.00 |
| work | 0 | 0 | 2 | 0 | 0 | 1.00 |
| promo | 1 | 0 | 0 | 0 | 0 | 0.00 |
| security | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 0.00 | 1.00 | 0.50 | — | 1.00 |  |

## Confusion matrix: bayes / action

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 0 | 3 | 0 | 0.00 |
| 1 | 0 | 1 | 1 | 0.50 |
| 2 | 0 | 0 | 3 | 1.00 |
| precision | — | 0.25 | 0.75 |  |

## Confusion matrix: bayes / phishing

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 1 | 0 | 1.00 |
| false | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | personal | billing | work | promo | security | recall |
|---|---|---|---|---|---|---|
| personal | 2 | 0 | 0 | 0 | 0 | 1.00 |
| billing | 0 | 1 | 0 | 0 | 0 | 1.00 |
| work | 0 | 0 | 2 | 0 | 0 | 1.00 |
| promo | 0 | 0 | 0 | 1 | 0 | 1.00 |
| security | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / action

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 3 | 0 | 0 | 1.00 |
| 1 | 0 | 1 | 1 | 0.50 |
| 2 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | 1.00 | 0.75 |  |

## Confusion matrix: systemone:clef / phishing

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 1 | 0 | 1.00 |
| false | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | personal | billing | work | promo | security | recall |
|---|---|---|---|---|---|---|
| personal | 2 | 0 | 0 | 0 | 0 | 1.00 |
| billing | 0 | 1 | 0 | 0 | 0 | 1.00 |
| work | 0 | 0 | 2 | 0 | 0 | 1.00 |
| promo | 0 | 0 | 0 | 1 | 0 | 1.00 |
| security | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / action

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 3 | 0 | 0 | 1.00 |
| 1 | 0 | 1 | 1 | 0.50 |
| 2 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | 1.00 | 0.75 |  |

## Confusion matrix: systemone:clef-flash / phishing

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 1 | 0 | 1.00 |
| false | 1 | 6 | 0.86 |
| precision | 0.50 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | personal | billing | work | promo | security | recall |
|---|---|---|---|---|---|---|
| personal | 2 | 0 | 0 | 0 | 0 | 1.00 |
| billing | 0 | 1 | 0 | 0 | 0 | 1.00 |
| work | 0 | 0 | 2 | 0 | 0 | 1.00 |
| promo | 0 | 0 | 0 | 1 | 0 | 1.00 |
| security | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / action

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 1 | 1 | 1 | 0.33 |
| 1 | 0 | 0 | 2 | 0.00 |
| 2 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | 0.00 | 0.50 |  |

## Confusion matrix: systemone:nimble / phishing

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 1 | 0 | 1.00 |
| false | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | personal | billing | work | promo | security | recall |
|---|---|---|---|---|---|---|
| personal | 2 | 0 | 0 | 0 | 0 | 1.00 |
| billing | 0 | 1 | 0 | 0 | 0 | 1.00 |
| work | 0 | 0 | 2 | 0 | 0 | 1.00 |
| promo | 0 | 0 | 0 | 1 | 0 | 1.00 |
| security | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / action

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 1 | 0 | 2 | 0.33 |
| 1 | 0 | 0 | 2 | 0.00 |
| 2 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | — | 0.43 |  |

## Confusion matrix: systemone:tev1 / phishing

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 1 | 0 | 1.00 |
| false | 0 | 7 | 1.00 |
| precision | 1.00 | 1.00 |  |
