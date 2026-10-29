# llama-server serving features (20261029-083933)

GPU NVIDIA GeForce RTX 3090, 580.178.04, llama.cpp 0.7.0-dev (build 11783, commit 339f3242c). Target `qwen3:14b`, context 8192, 128-token replies, 3 timed runs (median), flash attention on, temperature 0.

## Speculative decoding

Draft model: `/home/user/.local/share/crew-chief/gguf/Qwen3-0.6B-Q8_0.gguf`.

| Setting | Prompt | GPU MiB | Gen tok/s | Draft accepted % |
|---|---|---|---|---|
| no draft | prose | 21398 | 29.4 |  |
| no draft | structured | 21398 | 29.4 |  |
| ngram-mod | prose | 21398 | 29.3 | 5 |
| ngram-mod | structured | 21398 | 43.7 | 73 |
| draft max 8 | prose | 22938 | 29.9 | 17 |
| draft max 8 | structured | 22938 | 70.0 | 57 |
| draft max 16 | prose | 22938 | 23.6 | 9 |
| draft max 16 | structured | 22938 | 66.9 | 38 |
