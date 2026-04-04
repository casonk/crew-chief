# crew-chief

Local LLM service for portfolio-wide trivial inference tasks.  Runs [Ollama](https://ollama.com) inside a [Podman](https://podman.io) container and exposes a zero-dependency Python client so any repo can call it without cloud API access.

## Prerequisites

- [Podman](https://podman.io/getting-started/installation) ≥ 4.x
- Python ≥ 3.10 (for the client package)
- `curl` (for `scripts/pull_model.sh` and `scripts/status.sh`)

## Quick start

```bash
# 1. Build the image and start the service
bash scripts/start.sh

# 2. Pull a model (default: llama3.2)
bash scripts/pull_model.sh

# 3. Verify the service is healthy
bash scripts/status.sh
```

## Python client

Install in any portfolio repo:

```bash
pip install -e ./util-repos/crew-chief
```

Then use it:

```python
from crew_chief import CrewChiefClient

client = CrewChiefClient()                     # reads CREW_CHIEF_URL / CREW_CHIEF_MODEL env vars

# Single-turn generation
answer = client.generate("Summarise this in one sentence: ...")
print(answer)

# Multi-turn chat
reply = client.chat([
    {"role": "system", "content": "You are a concise assistant."},
    {"role": "user", "content": "What year was Python 3.10 released?"},
])
print(reply)

# Health check
if not client.health():
    print("Service is not running — start it with scripts/start.sh")

# List available models
for model in client.list_models():
    print(model)
```

## CLI

```bash
crew-chief generate "What is the capital of France?"
crew-chief health
crew-chief models
crew-chief --model mistral generate "Translate 'hello' to Spanish."
```

## Configuration

All settings are controlled through environment variables:

| Variable | Default | Description |
|---|---|---|
| `CREW_CHIEF_URL` | `http://localhost:11434` | Ollama service base URL |
| `CREW_CHIEF_MODEL` | `llama3.2` | Model to use for requests |
| `CREW_CHIEF_TIMEOUT` | `60` | HTTP timeout in seconds |
| `CREW_CHIEF_PORT` | `11434` | Host port for the container |
| `CREW_CHIEF_CONTAINER` | `crew-chief` | Podman container name |
| `CREW_CHIEF_IMAGE` | `crew-chief:latest` | Podman image name |
| `CREW_CHIEF_MODELS_VOLUME` | `crew-chief-models` | Volume for persisted model weights |

Copy `config/ollama/config.env.example` to `config/ollama/config.env` and adjust as needed.

## Container management

```bash
bash scripts/start.sh        # build (if needed) + start
bash scripts/stop.sh         # stop
bash scripts/status.sh       # container state + service health
bash scripts/pull_model.sh mistral   # pull a different model
```

## Running tests

```bash
pip install -e .
pytest -q
```

Tests are fully offline — no Ollama service required.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
