# Task benchmark: mail-triage (20261029-052702)

Triage an incoming email: its kind, how much attention it needs, and whether it looks like phishing. All messages are synthetic. Baseline rules were written against the dev split only.

16 items (dev split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | category acc | action acc | phishing acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 0.81 | 0.88 | 1.00 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 0.88 | 0.81 | 0.94 | 0.206 | 0 | 0 | 123.6 | 133.0 |
| systemone:nimble | 0.94 | 0.50 | 1.00 | 0.331 | 0 | 0 | 167.4 | 204.4 |
| ollama:qwen3:14b | 0.81 | 0.44 | 1.00 | — | 0 | 0 | 450.5 | 475.2 |
