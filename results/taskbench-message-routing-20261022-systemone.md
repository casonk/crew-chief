# Task benchmark: message-routing (20261022)

Route an incoming chat/email message the way the crew-chief listener must: intent, urgency, and the risk of any action it asks for. All messages are synthetic.

30 items. Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | intent acc | urgent acc | risk acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| systemone:clef-flash | 0.97 | 1.00 | 0.93 | 0.062 | 0 | 0 | 120.1 | 131.2 |
| systemone:nimble | 0.90 | 1.00 | 0.93 | 0.090 | 0 | 0 | 143.1 | 147.5 |
| systemone:tev1 | 0.93 | 0.80 | 0.87 | 0.200 | 0 | 0 | 106.1 | 127.0 |
| ollama:qwen3:14b | 0.93 | 1.00 | 0.97 | — | 0 | 0 | 421.4 | 434.7 |

## Conditions

Ollama 0.40.8 (upgraded from 0.20.2 the same day), RTX 3090, GPU cleared
with an exclusive lease before each run. `systemone:*` runners call Ollama's
`/v1/systemone` decision endpoint once per item (all three questions);
`ollama:qwen3:14b` makes one JSON-schema-constrained chat call per item.

| Model | Family | Parameters | Quantization | Disk |
|---|---|---|---|---|
| clef-flash | clef (decision, vision) | 9.1B | Q8_0 | 10 GB |
| nimble | qwen35 (decision) | 9.0B | Q8_0 | 9.5 GB |
| tev1 | qwen35 (decision) | 4.3B | Q8_0 | 4.6 GB |

## Findings

- Decision models answer all questions in one call in 106-143 ms with
  per-option probabilities, against 421 ms for qwen3:14b with no
  probabilities.
- Calibration (Brier, lower is better): clef-flash 0.062, nimble 0.090,
  tev1 0.200; the earlier llama.cpp single-token runners scored 0.235-0.247
  (`taskbench-message-routing-20261021.md`).
- clef-flash matches or beats every chat model tested on accuracy.
- The Ollama upgrade cut qwen3:14b's per-call time for this task from
  ~1.1 s (0.20.2) to 421 ms.
- Same 30 synthetic items as the first run; a held-out set is still needed
  before choosing a production model.
