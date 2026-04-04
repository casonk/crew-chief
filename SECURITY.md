# Security Policy

## Reporting a vulnerability

Please do not open public GitHub issues for security vulnerabilities.

Report issues privately via GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) feature, or contact the maintainer directly.

## Scope

- The `crew-chief` service exposes Ollama's REST API on `localhost:11434` by default.
  Do not expose this port on a public network interface without adding authentication.
- Model weights stored in the `crew-chief-models` Podman volume contain no user credentials.
- The Python client sends prompts over HTTP; avoid passing secrets or PII in prompt text.
