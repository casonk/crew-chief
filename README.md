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

Decision workloads (routing, categorization, schema filling) are scored with
`crew-chief taskbench`; see [docs/task-benchmarks.md](docs/task-benchmarks.md).

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

## Test-based local model benchmark

`scripts/test_benchmark.py` measures whether a local coding model can repair a
known regression and pass a repository's existing tests. Each attempt clones
the selected repository at one commit, applies a task patch that must make the
suite fail, and runs a restricted crew-chief agent with only read, exact text
replacement, and fixed test tools. It then reruns the same suite. A pass requires
an actual code change, a green suite, and no edits outside the task's allowlist.

Try the included task against this repository's full pytest suite:

```bash
python3 scripts/test_benchmark.py \
  --repo . \
  --task benchmarks/tasks/client-url-trim.json \
  --models llama3.2:3b-instruct-q8_0 qwen3:14b-q8_0 \
  --runs 3 --agent-timeout 180
```

The command writes ignored, local `results/test-bench-*.json` and `.html` files.
It also updates `results/test-bench-latest.html` and `.json` symlinks. The HTML
report is linked from the existing benchmark page when `results/` is served as
a static site. Open the HTML file in a browser for the **UI**: it shows pass/fail, test counts,
agent time, and total time for each trial. The JSON also records the base commit,
task patch hash, model digests and architecture metadata, Ollama version, and GPU. These local results can
contain model replies. Since the benchmark site serves `results/`, use `--out`
with a directory outside `results/` for reports that should stay off that site;
review any result before sharing it beyond the site's existing access controls.
The command exits nonzero if any trial fails; failure is a benchmark outcome.

### Replay repository evolution

Historical cases evaluate whether a model can bring an older checkout into
compliance with tests added later. Each case names a `before` commit, an `after`
commit, the changed test files, and the source paths the agent may edit. The
runner checks that the old suite passes, the selected new tests fail on old
source, and the same suite passes at the after commit. It then gives the agent
only the old source and selected new tests in a disposable checkout; the
reference source fix is withheld. Changes to tests or other paths cannot pass.

Run the two reviewed crew-chief cases together:

```bash
python3 scripts/test_benchmark.py \
  --repo . \
  --task benchmarks/tasks/history-cli-cwd.json \
  --task benchmarks/tasks/history-service-reply.json \
  --models llama3.2:3b-instruct-q8_0 qwen3:14b-q8_0 \
  --runs 3 --agent-timeout 180
```

The HTML report compares old-suite, new-test-on-old-source, reference, and
agent outcomes for each case. It separates agent timeouts and process errors
from completed trials that leave tests failing, and records tool-call attempts.
These are case-specific results, not a claim that a model can migrate every
older repository. Use several reviewed cases and trials before drawing a
broader conclusion.

For a cross-repository sweep, use the reviewed public suite from the portfolio
root. Each case resolves its checkout relative to `--portfolio-root`; task paths
resolve relative to the suite file. The resulting HTML identifies the repository
for each historical review and trial:

```bash
python3 scripts/test_benchmark.py \
  --suite benchmarks/public-history-suite.json \
  --portfolio-root ../.. \
  --models llama3.2:latest mistral:latest aya-expanse:8b qwen3:14b \
  --runs 1 --agent-timeout 120
```

The tracked suite contains only repositories verified public in the portfolio
visibility registry. Keep private cases in an ignored local suite and send their
reports only to an appropriately private location. Before a full agent sweep,
probe each model's Ollama tool-call behavior: a model that the server rejects
for tool calling cannot complete this benchmark regardless of coding ability.

To benchmark another repository, create a task JSON and a unified diff patch
like the example under `benchmarks/tasks/`. Use that repository's real test
command and identify only the source paths the agent may edit. The baseline
suite must fail after the patch; a passing or timed-out baseline is invalid.
Run several trials before comparing stochastic models. The existing
`scripts/benchmark.py` continues to measure inference speed separately.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
