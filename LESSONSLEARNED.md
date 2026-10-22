# LESSONSLEARNED.md

Tracked durable lessons for `crew-chief`.
Unlike `CHATHISTORY.md`, this file should keep only reusable lessons that should change how future sessions work in this repo.

## How To Use

- Read this file after `AGENTS.md` and before `CHATHISTORY.md` when resuming work.
- Add lessons that generalize beyond a single session.
- Keep entries concise and action-oriented.
- Do not use this file for transient status updates or full session logs.

## Lessons

- **Historical test replay needs three independent checks.** Run the old suite
  on the before commit (green), apply only selected tests from the after commit
  to old source (red), and run the same suite at the after commit (green).
  Withhold the reference source fix from the agent, stage injected tests before
  scoring edits, and reject any agent change to tests or unapproved paths.
  Report tool-use failures, agent errors, and timeouts separately from a
  completed code edit that leaves tests failing.

- **Probe each installed model tag for structured tool calls before a coding
  sweep.** Use the same Ollama provider and a tiny tool schema, then check the
  returned tool name and argument shape. Installed tags can return HTTP 400
  for tool calling or a call with unusable arguments even when text inference
  works. Record that capability separately from repair outcomes. For the
  historical suite, prefer cases where later tests fail by assertion on old
  source; import or collection errors are less precise behavioral evidence.

- **Check authenticated HTML delivery after updating reports served by Caddy.**
  The benchmark site needs `httpd_sys_content_t` on report files. Copying HTML
  from `/tmp` with `cp -a` kept `user_tmp_t`, causing direct report URLs to
  return 403 and the symlink index to fall back to directory browsing. Generate
  in `results/` or run `restorecon` after staging, then verify the root and
  latest report return HTTP 200 with `Content-Type: text/html`.

- **Static benchmark links need a stable target and generator support.** The
  benchmark site serves `results/` with `latest.html` as its index. When adding
  another report type, link it from both report generators and update a stable
  `*-latest.html` symlink after each run. Reports in `results/` are available to
  everyone with site access, so write sensitive trials elsewhere with `--out`.

- **Test-outcome benchmarks need a failing baseline in a disposable checkout.**
  Keep the task patch and test command fixed across models. Verify that the
  seeded failure is a completed test failure before starting an agent; score
  the final suite and allowed file changes, not the model's written claim.
  For this repo's local benchmark, expose only read, exact replacement, and
  fixed test tools to the model, and keep JSON/HTML reports gitignored.

- **CUDA GPU passthrough in rootless Podman requires six categories of host resources**: (1) device nodes (`/dev/nvidia0`, `/dev/nvidiactl`, `/dev/nvidia-uvm`, `/dev/nvidia-uvm-tools`, `/dev/nvidia-modeset`, `/dev/nvidia-caps/*`), (2) `--security-opt label=disable` for SELinux Enforcing hosts, (3) `--security-opt seccomp=unconfined` so CUDA ioctl syscalls are not blocked, (4) the driver API lib (`libcuda.so.1`), (5) the management lib (`libnvidia-ml.so.1`), and (6) the three CUDA runtime JIT/compiler libs that `libcuda.so.1` dlopen()s: `libnvidia-ptxjitcompiler.so.1`, `libnvidia-nvvm.so.4`, and `libnvidia-gpucomp.so.<version>`. Without categories 3 or 6 the GPU is detected and VRAM allocation succeeds but the first compute kernel crashes with "CUDA error: unknown error / exit status 2". Always resolve symlinks to the real versioned files before mounting (use `readlink -f`) to avoid dangling soname links inside the container.
- **`libnvidia-gpucomp.so` has a version-specific soname** (e.g. `libnvidia-gpucomp.so.580.142`) with no `.so.1` alias, so it must be mounted under its full versioned basename; use a glob over the host lib dir to stay driver-version-agnostic.

- Document the repository around its real execution, curation, or integration flow instead of only the top-level folder list.
- Keep local-only, private, reference-only, or generated boundaries explicit so published or runtime behavior is not confused with offline material or non-committable inputs.
- **Always run `pre-commit run --all-files && pytest -q` before every commit, without exception.** ruff-format and ruff lint auto-fix files on the first run (exit 1); re-run immediately after to confirm clean (exit 0), then stage the formatter's changes and commit. Skipping this is what causes CI failures. The check takes under 5 seconds and must not be omitted even for "docs-only" or "trivial" changes — formatting violations have appeared in `.py` files touched incidentally.
- Re-run repo-appropriate validation after changing generated artifacts, diagrams, workflows, or other CI-facing files so formatting and compatibility issues are caught before push.
- The Python client (`crew_chief.client`) is intentionally stdlib-only; keep it dependency-free so any portfolio repo can install it without pulling in extra transitive dependencies.
- Model weights live in the named Podman volume `crew-chief-models`, not in the container image itself; rebuilding the image does not lose pulled models.
- The `config/ollama/config.env` file contains host-specific Ollama env vars and must stay gitignored; commit only the `.example` template.
- **Example/template files are public — never put real values in them, even commented out.** `config/listener/config.toml.example` is tracked by git; KeePass entry paths, phone numbers, email addresses, file system paths, and any other instance-specific identifiers must use generic placeholders (e.g. `"your-keepass-entry-path"`). Real values belong only in the gitignored `config/listener/config.toml`. The same rule applies to `config/env.example` and any other `.example` file in this repo.
- **auto-pass KeePass entry paths are sensitive identifiers.** They reveal the structure of your password database and may expose account names or service identifiers. Treat them like passwords: store them only in gitignored local config files, never in committed example templates or documentation.
- **Local tool-capable models can emit plain-text pseudo tool-call JSON instead of real tool uses.** In `Agent.run`, treat content like `{"name": "greeting", "parameters": {...}}` as malformed function-call output for conversational prompts: retry once with an explicit correction, then fall back to plain text rather than showing raw JSON to the user.
- **Pseudo tool-call detection must ignore real schema/examples but still catch meta-preface leaks.** If a reply ends with a pseudo tool object such as `{"name": "shell", "parameters": {...}}` after reasoning text like "Since there's no explicit request...", treat it as malformed tool output. Do not do that when the user explicitly asked for a JSON/schema/example shape, or when the assistant clearly labels the object as an example.
- **Greeting-prefixed command requests are still command requests.** When classifying prompts in `Agent.run`, do not treat messages like `"hi, what's the uptime?"` as conversational for fallback handling; live system requests must stay on the shell-enforcement path even if they begin with a greeting.
- **CLI-backed providers must fence transcript-like user input as literal text.** `claude` / `codex` providers flatten structured history into a single prompt string, so a user message containing lines like `[System]`, `User:`, or `Assistant:` can be misread as active prompt structure. Detect that shape in `_messages_to_prompt()` and wrap it with an explicit "this is the user's message" preface instead of sending it raw.
- **pre-commit tool versions must exactly match CI versions.** Mismatches silently pass locally and fail in CI. The ruff v0.4.4 pre-commit pin lacked src-layout auto-detection and accepted a wrong import sort order that CI's v0.15.9 rejected. Keep `.pre-commit-config.yaml` rev values in sync with the versions pinned in `.github/workflows/ci.yml`.
- **intake pipeline emails must be excluded from crew-chief processing.** The receipt-intake pipeline sends notifications FROM and TO the same Gmail address with an `[intake]` subject prefix. crew-chief trusts that address, so it processed receipt notifications as user commands and replied — triggering a self-feeding loop. Add subject-prefix exclusion (e.g. `subject_exclude_patterns = ["[intake]*"]`) to `GmailConfig` so intake emails are dropped before any LLM or dispatch processing. This is a tracked backlog item.
- **Keep the Continue config keyless and model-accurate.** `~/.continue/config.yaml` is plain text and editor local history keeps copies of every save, so literal `apiKey:` values leak easily; reference keys as `${{ secrets.NAME }}` resolved from `~/.continue/.env` (mode 600) instead. List only models that are pulled and tool-capable, and do not leave a 3B model as the selection — it fabricates commands instead of calling tools.
- **Same-address self-email is architecturally ambiguous.** When an inbox receives mail from its own address, crew-chief cannot distinguish a legitimate user command from an intake notification or its own loop reply based on sender alone. The reply marker and auto-reply header guards stop crew-chief's own replies; subject-prefix or Gmail-label filtering is needed to stop third-party pipelines using the same address.
