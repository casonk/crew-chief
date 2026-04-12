# REFS-PUBLIC.md - Public References

> Record external public repositories, datasets, documentation, APIs, or other
> public resources that this repository utilizes or depends on.
> This file is tracked and intentionally kept free of private or local-only details.

## Public Repositories

- https://github.com/ollama/ollama - upstream local LLM runtime used by the service layer

## Public Datasets and APIs

- https://ollama.com/ - local inference runtime and model distribution surface used by this repo

## Documentation and Specifications

- https://podman.io/ - container runtime reference for local service deployment
- https://podman.io/getting-started/installation - Podman installation guidance

## Notes

- crew-chief is intentionally local-first and does not require a cloud inference API by default. Public refs only cover the local runtime stack it wraps.
