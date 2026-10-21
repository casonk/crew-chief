# Continue CLI (`cn`) on crew-chief

How to run the [Continue](https://docs.continue.dev/) CLI as a local coding
agent against the crew-chief Ollama service, and how to add metered cloud
models without putting API keys in the config.

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

## Cloud models and API keys

Prefer local models and subscription CLIs (Claude Code, Codex) for routine
work; API-key models are metered and cost more per token. They remain useful
occasionally, so the config can list them, but never with a literal key.

- Reference a secret instead of pasting the key:

  ```yaml
  - name: GPT-5 Mini
    provider: openai
    model: gpt-5-mini
    apiKey: ${{ secrets.OPENAI_API_KEY }}
  ```

- `cn` resolves `secrets.NAME` from the process environment first, then
  `~/.continue/.env`, then `<cwd>/.continue/.env` and `<cwd>/.env`. Keep the
  key in `~/.continue/.env` with mode `600`:

  ```bash
  install -m 600 /dev/null ~/.continue/.env   # once
  # then add a line: OPENAI_API_KEY=<key>
  ```

- Why not in `config.yaml`: the file is plain text, often opened in an
  editor, and editor local history (for example
  `~/.config/VSCodium/User/History/`) keeps a copy of every saved version.
- If a key does end up in the config, revoke it at the provider first, then
  remove it from the config and from any editor history snapshots.

## Troubleshooting

- `[FEATURE FLAGS] Feature flags quota limit exceeded` lines come from
  Continue's own telemetry backend and are harmless.
- `ollama: command not found` on the host is expected: Ollama runs inside the
  `crew-chief` container. Use `podman exec -it crew-chief ollama ...` or the
  `crew-chief` CLI. Do not install a host `ollama` package; it competes for
  port 11434.
