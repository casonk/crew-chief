# Task benchmark: backlog-triage (20261031-020215)

Sort a new backlog entry into a group and a repository, or answer unknown. Repositories, groups and entries are synthetic. The keyword baseline was written against the dev split only.

52 items (dev split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | group acc | repo acc | group macro F1 | repo macro F1 | Brier (mean) | invalid | errors | median ms | p90 ms | score: interactive | score: batch |
|---|---|---|---|---|---|---|---|---|---|---|---|
| rules | 1.00 | 0.86 | 1.00 | 0.86 | — | 0 | 0 | 0.0 | 0.0 | 0.953 | 0.936 |
| systemone:tev1 | 0.25 | 0.65 | 0.44 | 0.70 | 0.695 | 0 | 0 | 140.3 | 172.0 | gated | gated |
| systemone:clef-flash | 0.56 | 0.92 | 0.49 | 0.92 | 0.339 | 0 | 0 | 182.0 | 186.0 | gated | gated |
| systemone:nimble | 0.48 | 0.86 | 0.42 | 0.87 | 0.532 | 0 | 0 | 208.5 | 217.3 | gated | gated |
| systemone:clef | 0.75 | 0.96 | 0.59 | 0.96 | 0.276 | 0 | 0 | 893.0 | 900.2 | 0.601 | 0.829 |
| ollama:qwen2.5-coder:7b | 0.21 | 0.61 | 0.36 | 0.63 | — | 0 | 0 | 169.6 | 272.7 | gated | gated |

Scores (accuracy averaged over questions; relative speed is measured against the runners in this table; `gated` fails a profile's gate):
- `interactive`: 0.7 accuracy + 0.3 speed; full speed credit at 100 ms or less, none at 1000 ms or more, 0.3 of it from p90; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.8, p90 <= 1500 ms; ties within 0.02
- `batch`: 0.95 accuracy + 0.05 speed; full speed credit at 500 ms or less, none at 10000 ms or more; 0.5 of speed is relative to the fastest and slowest performer; gates: accuracy >= 0.85; ties within 0.01

## Confusion matrix: rules / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 40 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| doc | 0 | 2 | 0 | 0 | 0 | 0 | 1.00 |
| sec | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |

## Confusion matrix: rules / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| torrent-ui | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| session-viewer | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.50 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 1 | 0.75 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 1 | 0.75 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 1.00 |
| notifier | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 1 | 0.50 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 1.00 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 3 | 0 | 0.75 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 0.80 | 0.80 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.80 | 1.00 | 0.50 |  |

## Confusion matrix: systemone:tev1 / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 3 | 0 | 4 | 0 | 5 | 28 | 0.07 |
| doc | 0 | 1 | 0 | 0 | 0 | 1 | 0.50 |
| sec | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 1 | 0 | 1 | 0.50 |
| health | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 1.00 | 1.00 | 0.33 | 1.00 | 0.29 | 0.12 |  |

## Confusion matrix: systemone:tev1 / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.75 |
| list-manager | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 2 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.50 |
| torrent-ui | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| session-viewer | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.25 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0.75 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 3 | 0.25 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 2 | 0.50 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 1 | 0.75 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 2 | 0.50 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1 | 0.75 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 | 0.50 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.19 |  |

## Confusion matrix: systemone:clef-flash / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 20 | 1 | 4 | 0 | 4 | 11 | 0.50 |
| doc | 0 | 1 | 1 | 0 | 0 | 0 | 0.50 |
| sec | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 1 | 0 | 1 | 0.50 |
| health | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 1 | 0 | 3 | 0.75 |
| precision | 1.00 | 0.50 | 0.29 | 0.50 | 0.33 | 0.20 |  |

## Confusion matrix: systemone:clef-flash / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.75 |
| torrent-ui | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| session-viewer | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 0.75 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 1.00 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 | 0.75 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 1.00 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.75 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 | 0.75 | 0.80 | 1.00 | 1.00 |  |

## Confusion matrix: systemone:nimble / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 15 | 4 | 6 | 3 | 7 | 5 | 0.38 |
| doc | 0 | 1 | 1 | 0 | 0 | 0 | 0.50 |
| sec | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| research | 1 | 0 | 0 | 1 | 0 | 0 | 0.50 |
| health | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 0.94 | 0.20 | 0.22 | 0.25 | 0.22 | 0.44 |  |

## Confusion matrix: systemone:nimble / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 3 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.75 |
| torrent-ui | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0.75 |
| session-viewer | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 0.75 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 1 | 0.75 |
| secret-vault | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 0.75 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 | 0.75 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 1.00 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0.75 |
| precision | 1.00 | 1.00 | 0.75 | 1.00 | 0.67 | 1.00 | 1.00 | 1.00 | 1.00 | 0.60 | 0.80 | 1.00 | 0.75 |  |

## Confusion matrix: systemone:clef / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 30 | 1 | 4 | 0 | 4 | 1 | 0.75 |
| doc | 0 | 1 | 1 | 0 | 0 | 0 | 0.50 |
| sec | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 2 | 0 | 0 | 1.00 |
| health | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 2 | 0 | 2 | 0.50 |
| precision | 1.00 | 0.50 | 0.29 | 0.50 | 0.33 | 0.67 |  |

## Confusion matrix: systemone:clef / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| list-manager | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| torrent-ui | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| session-viewer | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 1 | 0 | 0 | 0 | 0.75 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 1.00 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 1 | 0 | 0 | 0.75 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 1.00 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.75 | 0.80 | 1.00 | 1.00 |  |

## Confusion matrix: ollama:qwen2.5-coder:7b / group

| expected \ answered | util | doc | sec | research | health | unknown | recall |
|---|---|---|---|---|---|---|---|
| util | 2 | 0 | 6 | 0 | 1 | 31 | 0.05 |
| doc | 0 | 1 | 0 | 0 | 0 | 1 | 0.50 |
| sec | 0 | 0 | 2 | 0 | 0 | 0 | 1.00 |
| research | 0 | 0 | 0 | 0 | 0 | 2 | 0.00 |
| health | 0 | 0 | 0 | 0 | 2 | 0 | 1.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 1.00 | 1.00 | 0.25 | — | 0.67 | 0.10 |  |

## Confusion matrix: ollama:qwen2.5-coder:7b / repo

| expected \ answered | scheduler-service | list-manager | media-library | torrent-ui | session-viewer | receipt-reader | local-llm | network-guard | secret-vault | notifier | resource-monitor | web-ingress | unknown | recall |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| scheduler-service | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.50 |
| list-manager | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| media-library | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.50 |
| torrent-ui | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1.00 |
| session-viewer | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.50 |
| receipt-reader | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0.50 |
| local-llm | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 0.50 |
| network-guard | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 1 | 0.75 |
| secret-vault | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 0 | 0 | 1.00 |
| notifier | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 0.00 |
| resource-monitor | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 1 | 0.75 |
| web-ingress | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 3 | 0.00 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 1.00 |
| precision | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.75 | 1.00 | — | 1.00 | — | 0.17 |  |
