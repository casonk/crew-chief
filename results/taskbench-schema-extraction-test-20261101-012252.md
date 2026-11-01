# Task benchmark: schema-extraction (20261101-012252)

Fill fixed fields from a short financial document: its kind, currency, and whether a due date is stated. All text is synthetic. Baseline rules were written against the dev split only.

8 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 16 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | kind acc | currency acc | due_date acc | kind macro F1 | currency macro F1 | due_date macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | — | 0 | 0 | 0.0 | 0.1 | 1.000 | 1.000 |
| bayes | 1.00 | 0.50 | 1.00 | 1.00 | 0.30 | 1.00 | 0.269 | 0 | 0 | 2.1 | 2.6 | 0.871 | gated |
| systemone:clef-flash | 1.00 | 1.00 | 0.88 | 1.00 | 1.00 | 0.87 | 0.061 | 0 | 0 | 301.3 | 11709.8 | gated | 0.928 |
| systemone:clef | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.000 | 0 | 0 | 1879.3 | 17746.1 | gated | 0.958 |
| systemone:nimble | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.001 | 0 | 0 | 366.6 | 8897.1 | gated | 0.969 |
| systemone:tev1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.003 | 0 | 0 | 229.4 | 4492.9 | gated | 0.977 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / kind

| expected \ answered | invoice | receipt | statement | quote | recall |
|---|---|---|---|---|---|
| invoice | 2 | 0 | 0 | 0 | 1.00 |
| receipt | 0 | 2 | 0 | 0 | 1.00 |
| statement | 0 | 0 | 2 | 0 | 1.00 |
| quote | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: rules / currency

| expected \ answered | usd | eur | gbp | none | recall |
|---|---|---|---|---|---|
| usd | 3 | 0 | 0 | 0 | 1.00 |
| eur | 0 | 2 | 0 | 0 | 1.00 |
| gbp | 0 | 0 | 2 | 0 | 1.00 |
| none | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: rules / due_date

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 3 | 0 | 1.00 |
| false | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: bayes / kind

| expected \ answered | invoice | receipt | statement | quote | recall |
|---|---|---|---|---|---|
| invoice | 2 | 0 | 0 | 0 | 1.00 |
| receipt | 0 | 2 | 0 | 0 | 1.00 |
| statement | 0 | 0 | 2 | 0 | 1.00 |
| quote | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: bayes / currency

| expected \ answered | usd | eur | gbp | none | recall |
|---|---|---|---|---|---|
| usd | 3 | 0 | 0 | 0 | 1.00 |
| eur | 1 | 1 | 0 | 0 | 0.50 |
| gbp | 0 | 2 | 0 | 0 | 0.00 |
| none | 0 | 1 | 0 | 0 | 0.00 |
| precision | 0.75 | 0.25 | — | — |  |

## Confusion matrix: bayes / due_date

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 3 | 0 | 1.00 |
| false | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / kind

| expected \ answered | invoice | receipt | statement | quote | recall |
|---|---|---|---|---|---|
| invoice | 2 | 0 | 0 | 0 | 1.00 |
| receipt | 0 | 2 | 0 | 0 | 1.00 |
| statement | 0 | 0 | 2 | 0 | 1.00 |
| quote | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / currency

| expected \ answered | usd | eur | gbp | none | recall |
|---|---|---|---|---|---|
| usd | 3 | 0 | 0 | 0 | 1.00 |
| eur | 0 | 2 | 0 | 0 | 1.00 |
| gbp | 0 | 0 | 2 | 0 | 1.00 |
| none | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / due_date

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 3 | 0 | 1.00 |
| false | 1 | 4 | 0.80 |
| precision | 0.75 | 1.00 |  |

## Confusion matrix: systemone:clef / kind

| expected \ answered | invoice | receipt | statement | quote | recall |
|---|---|---|---|---|---|
| invoice | 2 | 0 | 0 | 0 | 1.00 |
| receipt | 0 | 2 | 0 | 0 | 1.00 |
| statement | 0 | 0 | 2 | 0 | 1.00 |
| quote | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / currency

| expected \ answered | usd | eur | gbp | none | recall |
|---|---|---|---|---|---|
| usd | 3 | 0 | 0 | 0 | 1.00 |
| eur | 0 | 2 | 0 | 0 | 1.00 |
| gbp | 0 | 0 | 2 | 0 | 1.00 |
| none | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / due_date

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 3 | 0 | 1.00 |
| false | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / kind

| expected \ answered | invoice | receipt | statement | quote | recall |
|---|---|---|---|---|---|
| invoice | 2 | 0 | 0 | 0 | 1.00 |
| receipt | 0 | 2 | 0 | 0 | 1.00 |
| statement | 0 | 0 | 2 | 0 | 1.00 |
| quote | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / currency

| expected \ answered | usd | eur | gbp | none | recall |
|---|---|---|---|---|---|
| usd | 3 | 0 | 0 | 0 | 1.00 |
| eur | 0 | 2 | 0 | 0 | 1.00 |
| gbp | 0 | 0 | 2 | 0 | 1.00 |
| none | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / due_date

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 3 | 0 | 1.00 |
| false | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / kind

| expected \ answered | invoice | receipt | statement | quote | recall |
|---|---|---|---|---|---|
| invoice | 2 | 0 | 0 | 0 | 1.00 |
| receipt | 0 | 2 | 0 | 0 | 1.00 |
| statement | 0 | 0 | 2 | 0 | 1.00 |
| quote | 0 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / currency

| expected \ answered | usd | eur | gbp | none | recall |
|---|---|---|---|---|---|
| usd | 3 | 0 | 0 | 0 | 1.00 |
| eur | 0 | 2 | 0 | 0 | 1.00 |
| gbp | 0 | 0 | 2 | 0 | 1.00 |
| none | 0 | 0 | 0 | 1 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / due_date

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 3 | 0 | 1.00 |
| false | 0 | 5 | 1.00 |
| precision | 1.00 | 1.00 |  |
