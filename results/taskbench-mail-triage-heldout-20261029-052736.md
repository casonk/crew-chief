# Task benchmark: mail-triage (20261029-052736)

Triage an incoming email: its kind, how much attention it needs, and whether it looks like phishing. All messages are synthetic. Baseline rules were written against the dev split only.

8 items (heldout split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | category acc | action acc | phishing acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 0.62 | 0.50 | 0.75 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 1.00 | 0.75 | 1.00 | 0.129 | 0 | 0 | 121.6 | 10731.5 |
| systemone:nimble | 1.00 | 0.50 | 1.00 | 0.264 | 0 | 0 | 185.8 | 9640.8 |
| ollama:qwen3:14b | 1.00 | 0.50 | 1.00 | — | 0 | 0 | 456.6 | 9052.5 |
