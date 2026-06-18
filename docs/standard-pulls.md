# Standard Model Pulls

Reference for populating the `crew-chief-models` volume on a fresh deployment or
when onboarding a new machine. Pull commands use the Ollama REST API so they work
regardless of whether the Ollama CLI is on the host PATH.

Hardware target: **RTX 3090, 24 GB VRAM**, `/home` on a 1.9 TB NVMe.
Adjust the High and Flagship tiers if the target machine has less VRAM.

---

## Tier Overview

| Tier | VRAM budget | Purpose |
|---|---|---|
| **Fast** | ≤ 4 GB | Sub-second dispatch, health checks, trivial inference |
| **Mid** | 5–12 GB | General Q&A, moderate reasoning, code generation |
| **High** | 13–22 GB | Hard reasoning, large-context tasks |
| **Flagship** | 22–24 GB | Best available single-model quality within VRAM limit |
| **Specialist** | any | Domain-specific (translation, code, embeddings) |

---

## Baseline Pull Set

These are the models that should be present on every deployment. They cover
the full escalation chain plus the specialist tasks intake and other services depend on.

### Fast tier

```bash
# Default fast tier — 2 GB, crew-chief listener default
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "llama3.2:latest", "stream": false}'

# Fast tier Q8_0 — 3.5 GB, near-fp16 quality for simple tasks
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "llama3.2:3b-instruct-q8_0", "stream": false}'
```

### Mid tier

```bash
# General mid-tier — 9 GB, strong reasoning
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "qwen3:14b", "stream": false}'

# Mid tier Q8_0 — 16 GB, near-fp16 quality; preferred for hard tasks before
# escalating to a larger model
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "qwen3:14b-q8_0", "stream": false}'
```

### High tier

```bash
# High tier — 18 GB, 128K context, QAT quality; Google architecture diversity;
# strong for summarise/document/translate; slots between qwen3:14b-q8_0 and qwen3:32b
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "gemma3:27b-it-qat", "stream": false}'

# High tier flagship — 20 GB, best quality for pure-text tasks in 24 GB, 40K context
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "qwen3:32b", "stream": false}'

# High tier multimodal — 17 GB, text + image, 256K context
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "qwen3.5:27b", "stream": false}'
```

### Specialist models

```bash
# Code generation
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "qwen2.5-coder:7b", "stream": false}'

# Multilingual / translation (required by intake)
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "aya-expanse:8b", "stream": false}'
```

---

## Optional / Extended Set

Pull these after the baseline is in place, based on VRAM and storage budget.

```bash
# Larger general mid — 4.5 GB, strong for its size
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "llama3.1:8b", "stream": false}'

# Mistral 7B — 4 GB; useful as an independent second opinion in the mid tier
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "mistral:latest", "stream": false}'

# Qwen3.5 35B — 24 GB (tight; borderline with KV cache — test VRAM before routing)
curl -s -X POST http://localhost:11434/api/pull \
     -H "Content-Type: application/json" \
     -d '{"name": "qwen3.5:35b", "stream": false}'
```

---

## Bulk Pull Script

To pull the full baseline set in sequence:

```bash
#!/usr/bin/env bash
set -euo pipefail
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"

pull() {
    local name="$1"
    echo "Pulling $name ..."
    curl -s -X POST "$OLLAMA_URL/api/pull" \
         -H "Content-Type: application/json" \
         -d "{\"name\": \"$name\", \"stream\": false}" | \
         python3 -c "import sys,json; r=json.load(sys.stdin); print(r.get('status','done'))"
}

# Baseline
pull "llama3.2:latest"
pull "llama3.2:3b-instruct-q8_0"
pull "qwen3:14b"
pull "qwen3:14b-q8_0"
pull "gemma3:27b-it-qat"
pull "qwen3:32b"
pull "qwen3.5:27b"
pull "qwen2.5-coder:7b"
pull "aya-expanse:8b"

echo "Baseline pull complete."
```

---

## Checking Pull Status

```bash
# List models currently available
curl -s http://localhost:11434/api/tags | \
    python3 -c "
import sys, json
models = json.load(sys.stdin).get('models', [])
for m in models:
    print(f\"{m['name']:<40} {m['size'] // 1_000_000_000:.1f} GB\")
"

# Check if a background pull process is still running
ps aux | grep "curl.*ollama.*pull" | grep -v grep
```

---

## Notes

- Ollama pulls are resumable; an interrupted pull restarts from the last saved blob.
- The `crew-chief-models` Podman volume persists across container rebuilds and restarts — models do not need to be re-pulled after a `podman build`.
- Do not restart the `crew-chief-ollama` service while a pull is in progress; the in-flight curl request will be dropped and Ollama's resume logic will need to re-verify blobs on the next pull.
- See [`docs/model-reference.md`](model-reference.md) for VRAM budgets and the decision guide.
- After adding new models, re-run `python3 scripts/benchmark.py` and update the benchmark results section in `docs/model-reference.md`.
