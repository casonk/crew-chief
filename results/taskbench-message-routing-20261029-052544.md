# Task benchmark: message-routing (20261029-052544)

Route an incoming chat/email message the way the crew-chief listener must: intent, urgency, and the risk of any action it asks for. All messages are synthetic.

30 items (dev split). Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | intent acc | urgent acc | risk acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 0.97 | 0.90 | 0.97 | — | 0 | 0 | 0.0 | 0.0 |
| systemone:clef-flash | 0.97 | 1.00 | 0.93 | 0.062 | 0 | 0 | 118.3 | 139.7 |
| systemone:nimble | 0.90 | 1.00 | 0.93 | 0.090 | 0 | 0 | 142.8 | 147.4 |
| ollama:qwen3:14b | 0.93 | 1.00 | 0.97 | — | 0 | 0 | 415.2 | 441.4 |
