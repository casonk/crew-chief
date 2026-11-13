# K3s and Cilium pilot: the listener

Status: **prepared, not yet run on a cluster.** The files here are tested for what they say
(`tests/test_k3s_pilot.py`); `deploy/k3s/verify.sh` proves what the running pod does. Do not treat the
policy as working until that script passes on a real cluster.

## Why this service

`crew-chief-listener` polls a mailbox, accepts commands from trusted senders, and can run shell
commands and an agent loop. On the host it runs as the user, so a bad message that reaches the agent
can use anything the user can: every loaded deploy key, every local service, any network address. The
pilot answers one question: can that be reduced to "this pod, these four hostnames, these two
credentials" without breaking the service?

## What changes

| Host listener | Pilot pod |
|---|---|
| Runs as the user, sees the home directory and the SSH agent | Unprivileged uid, read-only root filesystem, no capabilities, no Kubernetes API token |
| Any outbound connection | Default deny; allowed: `imap.gmail.com:993`, `smtp.gmail.com:465/587`, `api.anthropic.com:443`, `api.openai.com:443`, cluster DNS |
| Host shell commands (`git`, `systemctl`, `journalctl`, `auto-pass`, `intake`...) | A five-command allowlist that works inside the container (`date`, `hostname`, `uname*`, `whoami`, `df*`) |
| Vault access at run time | Credentials read once by `make_secrets.py`, held in a Kubernetes Secret (encrypted at rest), mounted into this pod only |
| Ollama through the `ecu` gate | Not reachable by design in phase 1; cloud providers only |
| Signal and Gmail | Gmail only; Signal needs `signal-cli` and its account state, deferred |

The host's GPU, `ecu` leases, systemd timers and vault stay where they are.

## Phase 1 limits, stated plainly

- **Local models are not available to the pod.** The `ecu` gate listens on the host loopback. Phase 2
  options: bind it to the cluster bridge address behind a Cilium rule, or run an in-cluster relay.
- **No Signal.** Phase 2 packages `signal-cli` and a state volume.
- **Commands that manage the host are gone from the pod.** That is the point, but it means the pod
  cannot answer "show the failing job"; keep the host listener for that until a narrower channel exists.
- **Google's addresses are shared.** The FQDN rule allows whatever `imap.gmail.com` resolves to, on
  port 993 only. It limits the pod to those hostnames and ports; it does not prove which account.
- **One cluster node.** There is no high availability and no node isolation; the benefit is policy and
  secret scoping, not resilience.

## Run it

Pick the current stable versions first and record them in the table below.

1. **Cluster** (needs root; run it yourself):
   `sudo K3S_VERSION=<v> CILIUM_VERSION=<v> deploy/k3s/install-cluster.sh`
   It opens the pod and service ranges in firewalld, installs K3s without Flannel and without its own
   network policy, binds the API to loopback, encrypts Secrets, and installs Cilium with Hubble.
2. **Image**: `deploy/k3s/build-image.sh` (builds from a staged tree, then imports with `sudo`).
3. **Stop the host listener first.** Two listeners on one mailbox would both answer:
   `systemctl --user stop crew-chief-listener.service`
4. **Deploy**: `export KUBECONFIG=$HOME/.kube/k3s.yaml && deploy/k3s/apply.sh`
   It generates the confined config and the Secrets from local files, applies the policy before the
   pod, and waits for the rollout.
5. **Verify**: `deploy/k3s/verify.sh` must report every probe `ok`. Watch flows with
   `kubectl -n kube-system exec ds/cilium -- hubble observe --namespace crew-chief-listener`.

**Rollback**: `kubectl delete ns crew-chief-listener` and
`systemctl --user start crew-chief-listener.service`. The host unit is untouched throughout.

## What "done" means

- `verify.sh` passes: allowed hosts open, everything else closed, no API token, restricted context.
- The pod answers a test email from a trusted sender and ignores one from an untrusted sender.
- A week of Hubble logs shows no denied flow that the service needed, and no allowed flow that was
  unexpected.
- Then decide: widen to Signal and local models, move a second service, or stop.

## Versions used

| Component | Version | Date checked |
|---|---|---|
| K3s | _not yet chosen_ | |
| Cilium | _not yet chosen_ | |
