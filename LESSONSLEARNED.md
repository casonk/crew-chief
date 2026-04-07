# LESSONSLEARNED.md

Tracked durable lessons for `crew-chief`.
Unlike `CHATHISTORY.md`, this file should keep only reusable lessons that should change how future sessions work in this repo.

## How To Use

- Read this file after `AGENTS.md` and before `CHATHISTORY.md` when resuming work.
- Add lessons that generalize beyond a single session.
- Keep entries concise and action-oriented.
- Do not use this file for transient status updates or full session logs.

## Lessons

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
