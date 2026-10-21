# Continue CLI (`cn`) on crew-chief

How to run the [Continue](https://docs.continue.dev/) CLI as a local coding
agent against the crew-chief Ollama service, with no cloud API keys.

## Setup

1. Make sure the service is up and the models are pulled:

   ```bash
   bash scripts/status.sh
   crew-chief models
   ```

2. Install the keyless template as your Continue config (owner-only):

   ```bash
   install -m 600 config/continue/config.yaml.example ~/.continue/config.yaml
   ```

   Every `models:` entry must name a model listed by `crew-chief models`.
   Add or remove entries to match what is pulled on the host
   (see [standard-pulls.md](standard-pulls.md)).

3. Start a session and pick a model:

   ```bash
   cn                       # interactive; type /model to switch models
   cn -p "your prompt"      # one-shot, non-interactive
   ```

   `cn` remembers the last model you selected, which can override
   `defaultModel`. If a session opens on a small model, switch with `/model`.

## Choosing a model

| Model | Use |
|---|---|
| `qwen3:14b` | Default. Tool-capable, fits comfortably in 24 GB VRAM. |
| `qwen3:32b` / `qwen3.5:27b` | Harder tasks; slower, ~17–20 GB VRAM. |
| `llama3.1:8b`, `qwen2.5-coder:7b` | Quick edits and questions. |
| `gemma3:27b-it-qat` | Chat only — no tool calls. |

Avoid 3B-class models (`llama3.2`) for agent work: they invent commands and
loop on malformed tool calls. Only models whose Ollama capabilities include
`tools` can act as an agent:

```bash
curl -s localhost:11434/api/show -d '{"model":"qwen3:14b"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['capabilities'])"
```

## No API keys in the Continue config

The portfolio does not use cloud API keys for Continue. Keep
`~/.continue/config.yaml` limited to `provider: ollama` entries.

- Never paste an `apiKey:` value into the config. Continue writes the file
  in plain text, and editor local history (for example
  `~/.config/VSCodium/User/History/`) keeps copies of every saved version.
- If a cloud provider is ever needed, reference a Continue secret
  (`apiKey: ${{ secrets.OPENAI_API_KEY }}`) instead of a literal key.
- If a key does end up in the file, revoke it at the provider first, then
  remove it from the config and from any editor history snapshots.

## Troubleshooting

- `[FEATURE FLAGS] Feature flags quota limit exceeded` lines come from
  Continue's own telemetry backend and are harmless.
- `ollama: command not found` on the host is expected: Ollama runs inside the
  `crew-chief` container. Use `podman exec -it crew-chief ollama ...` or the
  `crew-chief` CLI. Do not install a host `ollama` package; it competes for
  port 11434.
