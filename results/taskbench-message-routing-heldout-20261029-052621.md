# Task benchmark: message-routing (20261029-052621)

Route an incoming chat/email message the way the crew-chief listener must: intent, urgency, and the risk of any action it asks for. All messages are synthetic.

10 items (heldout split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | intent acc | urgent acc | risk acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 0.90 | 0.90 | 0.90 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 0.90 | 1.00 | 1.00 | 0.081 | 0 | 0 | 129.4 | 143.6 |
| systemone:nimble | 1.00 | 1.00 | 1.00 | 0.021 | 0 | 0 | 144.5 | 151.4 |
| ollama:qwen3:14b | 1.00 | 1.00 | 1.00 | — | 0 | 0 | 417.6 | 451.3 |
