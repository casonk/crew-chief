# BACKLOG.md

Portfolio backlog for this repository. Pending items are candidates for execution —
manually or via crew-chief. Entries sourced from archility audit are tagged
`[archility:YYYY-MM-DD]`; manual entries use `[manual:YYYY-MM-DD]`.

The archility twice-weekly job populates this file automatically via `archility audit --write-backlog`.
To execute a backlog item with crew-chief: `crew-chief agent "Work on item: <item text>"`.
Mark items `[x]` when complete and move them to Done.

## Pending

- [ ] **vLLM inference backend** `[manual:2026-06-17]` — evaluate replacing Ollama with vLLM for higher throughput via paged attention and continuous batching. RTX 3090 24GB is capable. Worth testing on qwen3:14b and qwen3:32b. Primary benefit is concurrent request handling; for serialized personal-assistant use Ollama is sufficient. Benchmark: tokens/sec and TTFT vs Ollama at Q4_K_M. Reference: vllm-project/vllm, `vllm serve <model> --quantization awq`.

## In Progress

## Done
