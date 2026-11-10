# Task benchmark: message-routing (20261108-050506)

Route an incoming chat/email message the way the crew-chief listener must: intent, urgency, and the risk of any action it asks for. All messages are synthetic.

10 items (test split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

Protocol: All 30 train examples are in every prompt as worked examples. Only test items are scored, and none is ever shown to a model.

| Runner | intent acc | urgent acc | risk acc | intent macro F1 | urgent macro F1 | risk macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 0.90 | 0.90 | 0.90 | 0.88 | 0.87 | 0.86 | — | 0 | 0 | 0.0 | 0.0 | 0.930 | 0.905 |
| bayes | 0.70 | 0.90 | 0.90 | 0.71 | 0.87 | 0.86 | 0.295 | 0 | 0 | 0.9 | 1.1 | 0.883 | gated |
| systemone:clef | 0.90 | 1.00 | 1.00 | 0.88 | 1.00 | 1.00 | 0.037 | 0 | 0 | 1541.8 | 1549.1 | gated | 0.928 |
| systemone:clef-flash | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.029 | 0 | 0 | 370.1 | 381.5 | 0.738 | 0.969 |
| systemone:nimble | 0.90 | 1.00 | 0.80 | 0.88 | 1.00 | 0.83 | 0.181 | 0 | 0 | 390.8 | 407.0 | 0.668 | 0.875 |
| systemone:tev1 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.019 | 0 | 0 | 249.2 | 264.2 | 0.783 | 0.979 |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / intent

| expected \ answered | command | question | conversation | notification | recall |
|---|---|---|---|---|---|
| command | 3 | 0 | 0 | 0 | 1.00 |
| question | 0 | 2 | 0 | 0 | 1.00 |
| conversation | 1 | 0 | 1 | 0 | 0.50 |
| notification | 0 | 0 | 0 | 3 | 1.00 |
| precision | 0.75 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: rules / urgent

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 1 | 7 | 0.88 |
| precision | 0.67 | 1.00 |  |

## Confusion matrix: rules / risk

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 6 | 1 | 0 | 0.86 |
| 1 | 0 | 1 | 0 | 1.00 |
| 2 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 0.50 | 1.00 |  |

## Confusion matrix: bayes / intent

| expected \ answered | command | question | conversation | notification | recall |
|---|---|---|---|---|---|
| command | 2 | 0 | 1 | 0 | 0.67 |
| question | 1 | 1 | 0 | 0 | 0.50 |
| conversation | 0 | 0 | 2 | 0 | 1.00 |
| notification | 1 | 0 | 0 | 2 | 0.67 |
| precision | 0.50 | 1.00 | 0.67 | 1.00 |  |

## Confusion matrix: bayes / urgent

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 1 | 7 | 0.88 |
| precision | 0.67 | 1.00 |  |

## Confusion matrix: bayes / risk

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 6 | 1 | 0 | 0.86 |
| 1 | 0 | 1 | 0 | 1.00 |
| 2 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 0.50 | 1.00 |  |

## Confusion matrix: systemone:clef / intent

| expected \ answered | command | question | conversation | notification | recall |
|---|---|---|---|---|---|
| command | 3 | 0 | 0 | 0 | 1.00 |
| question | 1 | 1 | 0 | 0 | 0.50 |
| conversation | 0 | 0 | 2 | 0 | 1.00 |
| notification | 0 | 0 | 0 | 3 | 1.00 |
| precision | 0.75 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / urgent

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 8 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef / risk

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 7 | 0 | 0 | 1.00 |
| 1 | 0 | 1 | 0 | 1.00 |
| 2 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / intent

| expected \ answered | command | question | conversation | notification | recall |
|---|---|---|---|---|---|
| command | 3 | 0 | 0 | 0 | 1.00 |
| question | 0 | 2 | 0 | 0 | 1.00 |
| conversation | 0 | 0 | 2 | 0 | 1.00 |
| notification | 0 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / urgent

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 8 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:clef-flash / risk

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 7 | 0 | 0 | 1.00 |
| 1 | 0 | 1 | 0 | 1.00 |
| 2 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / intent

| expected \ answered | command | question | conversation | notification | recall |
|---|---|---|---|---|---|
| command | 3 | 0 | 0 | 0 | 1.00 |
| question | 1 | 1 | 0 | 0 | 0.50 |
| conversation | 0 | 0 | 2 | 0 | 1.00 |
| notification | 0 | 0 | 0 | 3 | 1.00 |
| precision | 0.75 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / urgent

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 8 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / risk

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 5 | 0 | 2 | 0.71 |
| 1 | 0 | 1 | 0 | 1.00 |
| 2 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 0.50 |  |

## Confusion matrix: systemone:tev1 / intent

| expected \ answered | command | question | conversation | notification | recall |
|---|---|---|---|---|---|
| command | 3 | 0 | 0 | 0 | 1.00 |
| question | 0 | 2 | 0 | 0 | 1.00 |
| conversation | 0 | 0 | 2 | 0 | 1.00 |
| notification | 0 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / urgent

| expected \ answered | true | false | recall |
|---|---|---|---|
| true | 2 | 0 | 1.00 |
| false | 0 | 8 | 1.00 |
| precision | 1.00 | 1.00 |  |

## Confusion matrix: systemone:tev1 / risk

| expected \ answered | 0 | 1 | 2 | recall |
|---|---|---|---|---|
| 0 | 7 | 0 | 0 | 1.00 |
| 1 | 0 | 1 | 0 | 1.00 |
| 2 | 0 | 0 | 2 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 |  |
