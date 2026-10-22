# Task benchmark: message-routing (20261022)

Route an incoming chat/email message the way the crew-chief listener must: intent, urgency, and the risk of any action it asks for. All messages are synthetic.

30 items. Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | intent acc | urgent acc | risk acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| systemone:clef | 0.97 | 1.00 | 1.00 | 0.037 | 0 | 0 | 723.8 | 728.3 |

## Conditions

Same task and host as `taskbench-message-routing-20261022-systemone.md`
(Ollama 0.40.8, RTX 3090 cleared with an exclusive lease). clef: 27.0B,
Q4_K_M, decision + vision; about 23 GB of GPU memory in use after the run.

## Finding

clef is the most accurate and best calibrated decision model measured
(Brier 0.037 vs 0.062 for clef-flash) but takes 724 ms per item, six times
clef-flash's 120 ms, and needs most of the GPU. clef-flash stays the default
candidate for high-volume routing; clef suits low-volume, high-stakes
decisions or a second opinion when clef-flash is unsure.
