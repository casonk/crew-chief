# Task benchmark: clockwork-invest-category (20261110-063526)

Sort a security or idea into a Clockwork To Invest category. Names are well-known public instruments and generic themes, not holdings. Baseline rules were written against the dev split only.

30 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 18 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.23 | 0.16 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.47 | 0.42 | 0.642 | 0 | 0 | 0.1 | 0.1 | gated | gated |
| systemone:clef-flash | 0.93 | 0.93 | 0.102 | 0 | 0 | 139.3 | 143.1 | 0.725 | 0.911 |
| systemone:clef | 1.00 | 1.00 | 0.010 | 0 | 0 | 826.6 | 836.0 | 0.704 | 0.966 |
| systemone:nimble | 0.97 | 0.97 | 0.065 | 0 | 0 | 160.8 | 164.6 | 0.771 | 0.947 |
| systemone:tev1 | 1.00 | 1.00 | 0.013 | 0 | 0 | 94.7 | 96.7 | 0.834 | 0.979 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 5 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Crypto | 5 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Bonds | 4 | 0 | 0 | 1 | 0 | 0 | 0.20 |
| REITs | 4 | 0 | 0 | 0 | 1 | 0 | 0.20 |
| Themes | 5 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| precision | 0.18 | — | — | 1.00 | 1.00 | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 3 | 1 | 0 | 1 | 0 | 0 | 0.20 |
| Crypto | 5 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Bonds | 0 | 0 | 0 | 5 | 0 | 0 | 1.00 |
| REITs | 4 | 0 | 0 | 0 | 1 | 0 | 0.20 |
| Themes | 2 | 1 | 0 | 0 | 0 | 2 | 0.40 |
| precision | 0.26 | 0.50 | — | 0.83 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 5 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 5 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 5 | 0 | 0 | 1.00 |
| REITs | 2 | 0 | 0 | 0 | 3 | 0 | 0.60 |
| Themes | 0 | 0 | 0 | 0 | 0 | 5 | 1.00 |
| precision | 0.71 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 5 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 5 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 5 | 0 | 0 | 1.00 |
| REITs | 0 | 0 | 0 | 0 | 5 | 0 | 1.00 |
| Themes | 0 | 0 | 0 | 0 | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 5 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 5 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 5 | 0 | 0 | 1.00 |
| REITs | 1 | 0 | 0 | 0 | 4 | 0 | 0.80 |
| Themes | 0 | 0 | 0 | 0 | 0 | 5 | 1.00 |
| precision | 0.83 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 5 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 5 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 5 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 5 | 0 | 0 | 1.00 |
| REITs | 0 | 0 | 0 | 0 | 5 | 0 | 1.00 |
| Themes | 0 | 0 | 0 | 0 | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |
