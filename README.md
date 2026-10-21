# crew-chief

Local LLM service for portfolio-wide trivial inference tasks.  Runs [Ollama](https://ollama.com) inside a [Podman](https://podman.io) container and exposes a zero-dependency Python client so any repo can call it without cloud API access.

If you enable the listener workflows that poll or respond through personal Signal or Gmail channels, the explicit consent reference is [`../../doc-repos/my-consent/messaging-and-email.md`](../../doc-repos/my-consent/messaging-and-email.md).

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

Install into the consuming repo's virtualenv:

```bash
. .venv/bin/activate          # the venv of the repo that will use the client
pip install -e ./util-repos/crew-chief
```

The virtualenv is not optional on current Debian, Ubuntu, Arch and openSUSE:
since [PEP 668](https://peps.python.org/pep-0668/) those distros refuse a
`pip install` into the system Python with `externally-managed-environment`.

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

## Coding agent on local models (beta)

`crew-chief code` opens Claude Code on a local model served by Ollama or
llama.cpp, with the session recorded for session-control:

```bash
crew-chief code --list            # tool-capable models
crew-chief code -m qwen3:32b      # start a session
crew-chief code -- --resume <id>  # reopen one
```

Which backend serves each model, and with what settings, comes from the
governed serving policy (`config/serving-policy.toml`, see
[docs/serving-policy.md](docs/serving-policy.md)); `crew-chief policy check
--live` reports drift.

See [docs/local-inference-roadmap.md](docs/local-inference-roadmap.md) for
options and the phased plan for further frontends, backends, and hardware.

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
| `CREW_CHIEF_CODE_MODEL` | `qwen3:14b` | Default model for `crew-chief code` |
| `CREW_CHIEF_CODE_CONTEXT` | `32768` | Context window `crew-chief code` reports to Claude Code |

Copy `config/ollama/config.env.example` to `config/ollama/config.env` and adjust as needed.

## Continue CLI (`cn`)

To use the local models as a coding agent through the Continue CLI, see
[docs/continue-cli.md](docs/continue-cli.md). The config template is
`config/continue/config.yaml.example`.

## Container management

```bash
bash scripts/start.sh        # build (if needed) + start
bash scripts/stop.sh         # stop
bash scripts/status.sh       # container state + service health
bash scripts/pull_model.sh mistral   # pull a different model
```

## Running tests

```bash
./bootstrap.sh
.venv/bin/pytest -q
```

`bootstrap.sh` creates `.venv`, installs the package in editable mode, and
verifies the `crew-chief` command runs. Pass `--listener` to include the
listener extra, or `--venv PATH` to build the environment elsewhere.

<details>
<summary>Why not <code>pip install -e .</code> directly?</summary>

Since [PEP 668](https://peps.python.org/pep-0668/), Debian, Ubuntu, Arch and
openSUSE mark the system Python as externally managed, and pip refuses to
install into it:

```
error: externally-managed-environment
```

Fedora still allows it, which is why the old instruction worked on some
machines and not others. Installing into a virtualenv is correct on all of
them, and on macOS and Windows too.

</details>

Tests are fully offline — no Ollama service required.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
