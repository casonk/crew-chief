# Task benchmark: clockwork-invest-category (20261101-012532)

Sort a security or idea into a Clockwork To Invest category. Names are well-known public instruments and generic themes, not holdings. Baseline rules were written against the dev split only.

12 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 18 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | category acc | category macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|
| rules | 0.17 | 0.05 | — | 0 | 0 | 0.0 | 0.0 | gated | gated |
| bayes | 0.42 | 0.31 | 0.698 | 0 | 0 | 0.2 | 0.2 | gated | gated |
| systemone:clef-flash | 0.83 | 0.78 | 0.246 | 0 | 0 | 143.5 | 179.3 | 0.638 | gated |
| systemone:clef | 1.00 | 1.00 | 0.022 | 0 | 0 | 1388.7 | 1400.5 | 0.700 | 0.961 |
| systemone:nimble | 0.92 | 0.91 | 0.163 | 0 | 0 | 166.4 | 187.4 | 0.705 | 0.895 |
| systemone:tev1 | 1.00 | 1.00 | 0.025 | 0 | 0 | 97.1 | 106.4 | 0.817 | 0.980 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Crypto | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Bonds | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| REITs | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Themes | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| precision | 0.17 | — | — | — | — | — |  |

## Confusion matrix: bayes / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 1 | 0 | 0 | 1 | 0 | 0 | 0.00 |
| Crypto | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Bonds | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| REITs | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Themes | 1 | 0 | 0 | 0 | 0 | 1 | 0.50 |
| precision | 0.25 | — | — | 0.67 | — | 1.00 |  |

## Confusion matrix: systemone:clef-flash / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| REITs | 2 | 0 | 0 | 0 | 0 | 0 | 0.00 |
| Themes | 0 | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 0.50 | 1.00 | 1.00 | 1.00 | — | 1.00 |  |

## Confusion matrix: systemone:clef / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| REITs | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Themes | 0 | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| REITs | 1 | 0 | 0 | 0 | 1 | 0 | 0.50 |
| Themes | 0 | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / category

| expected \ answered | Stocks | ETFs | Crypto | Bonds | REITs | Themes | recall |
|---|---|---|---|---|---|---|---|
| Stocks | 2 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| ETFs | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 |
| Crypto | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| Bonds | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| REITs | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| Themes | 0 | 0 | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |
