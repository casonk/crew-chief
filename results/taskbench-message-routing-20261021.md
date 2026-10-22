# Task benchmark: message-routing (20261021)

Route an incoming chat/email message the way the crew-chief listener must: intent, urgency, and the risk of any action it asks for. All messages are synthetic.

30 items. Accuracy per question; Brier is the multi-class Brier
score over questions where the runner reports probabilities (lower is better).

| Runner | intent acc | urgent acc | risk acc | Brier (mean) | invalid | errors | median ms | p90 ms |
|---|---|---|---|---|---|---|---|---|
| rules | 0.97 | 0.90 | 0.97 | — | 0 | 0 | 0.0 | 0.0 |
| ollama:llama3.2:latest | 0.80 | 0.83 | 0.83 | — | 0 | 0 | 1156.9 | 1456.0 |
| ollama:llama3.1:8b | 0.90 | 0.87 | 0.93 | — | 0 | 0 | 1100.7 | 1355.0 |
| ollama:qwen3:14b | 0.93 | 1.00 | 0.97 | — | 0 | 0 | 1104.2 | 1357.1 |
| llamacpp:qwen3:14b | 0.87 | 0.83 | 0.90 | 0.247 | 0 | 0 | 193.3 | 206.2 |
| llamacpp:qwen3:32b | 0.97 | 0.77 | 0.90 | 0.235 | 0 | 0 | 370.6 | 403.5 |

## Conditions

RTX 3090, GPU cleared with an exclusive lease (listener, Ollama models and
upscaler moved aside). Ollama 0.20.2 runners make one JSON-schema-constrained
call per item; llama.cpp (build 339f3242c) runners make one letter-constrained,
single-token call per question, so their latency covers three calls.
qwen3:32b on llama.cpp used its serving-policy configuration (32K, q8_0 KV).

## Caveats

- The `rules` baseline was written while looking at these 30 items, so it is
  fitted to them. Treat it as an upper bound for keyword rules, not a fair
  floor, until a held-out set exists.
- Ollama's per-call latency (~1.1 s) was the same for 3B and 14B models. Its
  timing fields show model work of 0.3-0.7 s per call; the rest is per-request
  overhead (load bookkeeping and, most likely, schema grammar setup). Small
  decisions pay that overhead every time.
- The llama.cpp runners answer each question with one constrained token and no
  reasoning, which costs accuracy on qwen3:14b (0.87/0.83/0.90 vs 0.93/1.00/0.97
  on Ollama) but gives per-option probabilities and ~65 ms per question.
