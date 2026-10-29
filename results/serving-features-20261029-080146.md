# llama-server serving features (20261029-080146)

GPU NVIDIA GeForce RTX 3090, 580.178.04, llama.cpp 0.7.0-dev (build 11783, commit 339f3242c). Target `qwen3:14b`, context 8192, 128-token replies, 3 timed runs (median), flash attention on, temperature 0.

## KV-cache type

| KV type | GPU MiB | Gen tok/s | Prompt tok/s |
|---|---|---|---|
| kv f16 | 10160 | 64.1 | 2434.0 |
| kv q8_0 | 9562 | 63.0 | 2357.1 |
| kv q4_0 | 9242 | 62.6 | 2331.9 |

## Prompt-cache reuse

Four turns over a shared ~6000-token prefix; each turn adds a new last line. Seconds are wall time per request.

| Setting | First turn s | Later turns s | Tokens evaluated later |
|---|---|---|---|
| cache_prompt off | 3.0 | 2.7 | 4854 |
| cache_prompt on | 2.99 | 0.55 | 10 |

## Parallel slots

Four concurrent requests.

| Setting | GPU MiB | Wall s | Aggregate tok/s | Per request tok/s |
|---|---|---|---|---|
| -np 1 | 10160 | 9.12 | 56.1 | 62.3 |
| -np 4 | 14000 | 4.11 | 124.5 | 37.5 |

## Speculative decoding

Draft model: `llama3.2:latest`.

| Setting | Prompt | GPU MiB | Gen tok/s | Draft accepted % |
|---|---|---|---|---|
| no draft | prose | 5856 | 116.3 |  |
| no draft | structured | 5856 | 117.4 |  |
| ngram-mod | prose | 5856 | 116.6 | 23 |
| ngram-mod | structured | 5856 | 585.9 | 95 |
| draft max 8 | prose | 8756 | 60.5 | 34 |
| draft max 8 | structured | 8756 | 112.8 | 76 |
| draft max 16 | prose | 8756 | 43.5 | 18 |
| draft max 16 | structured | 8756 | 103.8 | 60 |
