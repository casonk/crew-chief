# Deployment modes: the listener

The crew-chief **listener** (the Gmail and Signal command channel) runs three ways. You choose with one
setting, and **only the `k3s` mode needs a cluster**. If you just want the listener, you need Python and nothing
else. (The Ollama service is separate: see `scripts/start.sh` and the README.)

| Mode | What it is | Needs | Use it for |
|---|---|---|---|
| `dev` (default) | the listener in the foreground | Python 3.10+ | trying it, developing |
| `host` | the Clockwork-managed systemd user service | Python, systemd, Clockwork | a machine that runs it day to day |
| `k3s` | a pod in K3s with default-deny egress | K3s, podman, kubectl, the in-cluster registry | isolating a network-facing process |

The application code is identical in all three. Nothing under `src/` knows which mode it is in. The pod gets a
different *configuration* (`deploy/k3s/make_config.py` confines it: no Signal, cloud models only, a short command
allowlist), not different code.

## Choose a mode

```bash
deploy/deploy.sh mode                  # print the mode in effect and where it came from
deploy/deploy.sh up                    # run it in that mode
deploy/deploy.sh status | verify | down
```

The mode is read from, first match wins:

1. `--mode dev|host|k3s` on the command line
2. `CREW_CHIEF_DEPLOY_MODE` in the environment
3. `CREW_CHIEF_DEPLOY_MODE` in `config/deploy.local.env` (copy `config/deploy.example.env`; it is gitignored)
4. `dev`

An unknown value, or a config file that cannot be read, is an error, never a silent fallback.

## What each mode does

### dev
`up` runs `python3 -m crew_chief listen --config config/listener/config.toml` in the foreground (copy
`config/listener/config.toml.example` first; set `CREW_CHIEF_LISTENER_CONFIG` for another path).

### host
`up` enables `crew-chief-listener.service`. That unit is installed by Clockwork from its
`examples/crew-chief/listener-service.toml` (copy it to `*.local.toml` with real paths, then
`clockwork install --manifest <that file> --target systemd-user`); `up` tells you if it is missing.

### k3s
`up` refuses to start, and changes nothing, unless kubectl, podman and the in-cluster registry are present.
**Two listeners on one mailbox would answer every email twice**, so it stops the host listener first, then runs
`build-image.sh` (refuses uncommitted `src/`, because the pod runs what is committed), `apply.sh` and `verify.sh`.
If any step fails it scales the pod to 0 and restarts the host listener, so you are never left with neither.
Details, network policy and the runbook: [`k3s-cilium-pilot.md`](k3s-cilium-pilot.md).

## Switching

| From | To | Command |
|---|---|---|
| dev | host | stop the foreground process, then `deploy/deploy.sh --mode host up` |
| host | k3s | `deploy/deploy.sh --mode k3s up` (stops the host listener, deploys, verifies) |
| k3s | host | `deploy/deploy.sh --mode host up` (scales the pod to 0, starts the host listener) |
| any | stopped | `--mode host down`, or Ctrl-C in dev |

`--mode k3s down` is the same as `--mode host up`. The pod is left scaled to 0
(`kubectl delete ns crew-chief-listener` removes it). A marker in `~/.local/state/crew-chief/` records that the
pod was last handed the work, so `host up` knows to stop it.

## Settings that differ by mode

Secrets are never copied into a manifest. In k3s mode `apply.sh` resolves them from the host's vault and
config at deploy time (`make_secrets.py`), because the pod cannot reach the vault.

| Setting | Standalone (`dev`, `host`) | `k3s` |
|---|---|---|
| model chain | local Ollama first, then cloud | cloud only (`anthropic`, `openai`); no local backend in the pod |
| Signal channel | as configured | disabled |
| command allowlist | as configured | `date`, `hostname`, `uname`, `whoami`, `df` |
| file tools | as configured | `/tmp` only |
| network | the host's | default deny; only Gmail and the two model APIs |

## For contributors without K3s

- `pytest` needs no cluster: the deployment tests parse manifests and run the scripts against stub commands.
- Nothing under `deploy/k3s/` runs unless you select the `k3s` mode.
