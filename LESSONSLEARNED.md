# LESSONSLEARNED.md

Tracked durable lessons for `crew-chief`.
Unlike `CHATHISTORY.md`, this file should keep only reusable lessons that should change how future sessions work in this repo.

## How To Use

- Read this file after `AGENTS.md` and before `CHATHISTORY.md` when resuming work.
- Add lessons that generalize beyond a single session.
- Keep entries concise and action-oriented.
- Do not use this file for transient status updates or full session logs.

## Lessons

- Document the repository around its real execution, curation, or integration flow instead of only the top-level folder list.
- Keep local-only, private, reference-only, or generated boundaries explicit so published or runtime behavior is not confused with offline material or non-committable inputs.
- Re-run repo-appropriate validation after changing generated artifacts, diagrams, workflows, or other CI-facing files so formatting and compatibility issues are caught before push.
- The Python client (`crew_chief.client`) is intentionally stdlib-only; keep it dependency-free so any portfolio repo can install it without pulling in extra transitive dependencies.
- Model weights live in the named Podman volume `crew-chief-models`, not in the container image itself; rebuilding the image does not lose pulled models.
- The `config/ollama/config.env` file contains host-specific Ollama env vars and must stay gitignored; commit only the `.example` template.
