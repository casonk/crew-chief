# Task benchmark: backlog-triage (20261031-020412)

Sort a new backlog entry into a group and a repository, or answer unknown. Repositories, groups and entries are synthetic. The keyword baseline was written against the dev split only.

39 items (heldout split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | group acc | repo acc | group macro F1 | repo macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 0.97 | 0.82 | 0.98 | 0.83 | — | 0 | 0 | 0.0 | 0.0 | 0.928 | 0.903 |
| systemone:tev1 | 0.28 | 0.51 | 0.37 | 0.56 | 0.790 | 0 | 0 | 140.5 | 148.9 | gated | gated |
| systemone:clef-flash | 0.54 | 0.82 | 0.45 | 0.81 | 0.415 | 0 | 0 | 188.9 | 193.4 | gated | gated |
| systemone:nimble | 0.49 | 0.74 | 0.43 | 0.74 | 0.565 | 0 | 0 | 210.7 | 212.8 | gated | gated |
| systemone:clef | 0.74 | 0.82 | 0.67 | 0.81 | 0.318 | 0 | 0 | 897.1 | 906.5 | gated | gated |
| ollama:qwen2.5-coder:7b | 0.31 | 0.46 | 0.52 | 0.48 | — | 0 | 0 | 166.9 | 254.8 | gated | gated |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 20 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| doc | 1 | 7 | 0 | 0 | 0 | 0 | 0.88 |
| sec | 0 | 0 | 4 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 3 | 0 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 1 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 3 | 1.00 |
| precision | 0.95 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: rules / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.67 |
| torrent-ui | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.67 |
| session-viewer | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 0 | 0.67 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0.67 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 1 | 0.67 |
| resource-monitor | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0.67 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 1 | 0.67 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1.00 |
| precision | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 | 0.67 | 1.00 | 1.00 | 0.43 |  |

## Confusion matrix: systemone:tev1 / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 1 | 0 | 0 | 0 | 2 | 17 | 0.05 |
| doc | 0 | 2 | 3 | 0 | 0 | 3 | 0.25 |
| sec | 0 | 0 | 3 | 0 | 0 | 1 | 0.75 |
| research | 0 | 0 | 0 | 1 | 1 | 1 | 0.33 |
| health | 0 | 0 | 0 | 0 | 1 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 3 | 1.00 |
| precision | 1.00 | 1.00 | 0.50 | 1.00 | 0.25 | 0.12 |  |

## Confusion matrix: systemone:tev1 / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.67 |
| media-library | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.67 |
| torrent-ui | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0.33 |
| session-viewer | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.33 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 0.33 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 0.67 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 0.33 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 0.33 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.00 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 0.33 |
| unknown | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.67 |
| precision | 1.00 | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 | 1.00 | — | 1.00 | 0.10 |  |

## Confusion matrix: systemone:clef-flash / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 11 | 0 | 0 | 0 | 2 | 7 | 0.55 |
| doc | 0 | 4 | 1 | 0 | 0 | 3 | 0.50 |
| sec | 0 | 0 | 3 | 0 | 0 | 1 | 0.75 |
| research | 1 | 0 | 0 | 0 | 1 | 1 | 0.00 |
| health | 0 | 0 | 0 | 0 | 1 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 1 | 2 | 0.67 |
| precision | 0.92 | 1.00 | 0.75 | — | 0.20 | 0.14 |  |

## Confusion matrix: systemone:clef-flash / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| torrent-ui | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.67 |
| session-viewer | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 0 | 0.67 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0.67 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 0 | 0 | 0 | 0.67 |
| resource-monitor | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.33 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1.00 |
| unknown | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.67 |
| precision | 0.75 | 0.75 | 1.00 | 1.00 | 0.75 | 1.00 | 1.00 | 0.67 | 0.67 | 0.67 | 1.00 | 1.00 | 0.67 |  |

## Confusion matrix: systemone:nimble / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 10 | 2 | 1 | 2 | 1 | 4 | 0.50 |
| doc | 1 | 2 | 3 | 0 | 1 | 1 | 0.25 |
| sec | 0 | 0 | 3 | 0 | 0 | 1 | 0.75 |
| research | 1 | 0 | 0 | 1 | 1 | 0 | 0.33 |
| health | 0 | 0 | 0 | 0 | 1 | 0 | 1.00 |
| unknown | 0 | 1 | 0 | 0 | 0 | 2 | 0.67 |
| precision | 0.83 | 0.40 | 0.43 | 0.33 | 0.25 | 0.25 |  |

## Confusion matrix: systemone:nimble / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.67 |
| torrent-ui | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.67 |
| session-viewer | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0.33 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 0 | 0.67 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0.67 |
| notifier | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0.67 |
| resource-monitor | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 1 | 0.33 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1.00 |
| unknown | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.67 |
| precision | 1.00 | 0.60 | 0.67 | 1.00 | 0.75 | 1.00 | 1.00 | 0.67 | 1.00 | 0.67 | 1.00 | 1.00 | 0.33 |  |

## Confusion matrix: systemone:clef / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 14 | 0 | 2 | 0 | 1 | 3 | 0.70 |
| doc | 0 | 6 | 2 | 0 | 0 | 0 | 0.75 |
| sec | 0 | 0 | 4 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 2 | 1 | 0 | 0.67 |
| health | 0 | 0 | 0 | 0 | 1 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 1 | 2 | 0.67 |
| precision | 1.00 | 1.00 | 0.50 | 1.00 | 0.25 | 0.40 |  |

## Confusion matrix: systemone:clef / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.67 |
| media-library | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| torrent-ui | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.67 |
| session-viewer | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0.67 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0.67 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 0 | 0 | 0 | 0.67 |
| resource-monitor | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0.33 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1.00 |
| precision | 0.75 | 1.00 | 1.00 | 1.00 | 0.75 | 1.00 | 1.00 | 0.67 | 0.67 | 1.00 | 1.00 | 0.75 | 0.60 |  |

## Confusion matrix: ollama:qwen2.5-coder:7b / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 0 | 0 | 1 | 0 | 0 | 19 | 0.00 |
| doc | 0 | 4 | 2 | 0 | 0 | 2 | 0.50 |
| sec | 0 | 0 | 2 | 0 | 0 | 2 | 0.50 |
| research | 0 | 0 | 0 | 2 | 0 | 1 | 0.67 |
| health | 0 | 0 | 0 | 0 | 1 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 3 | 1.00 |
| precision | — | 1.00 | 0.40 | 1.00 | 1.00 | 0.11 |  |

## Confusion matrix: ollama:qwen2.5-coder:7b / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.00 |
| list-manager | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.33 |
| torrent-ui | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0.67 |
| session-viewer | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.33 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 2 | 0.33 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 2 | 0.33 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 1 | 0.67 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.00 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.00 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 2 | 0.33 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1.00 |
| precision | — | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.50 | 1.00 | — | — | 1.00 | 0.13 |  |
