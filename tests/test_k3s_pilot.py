"""The K3s/Cilium pilot: the confined config and the manifests' security invariants.

These run without a cluster. They prove the files say what the design promises; verify.sh proves the
running pod behaves that way.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - 3.10
    import tomli as tomllib  # type: ignore[no-redef]

yaml = pytest.importorskip("yaml")

DEPLOY = Path(__file__).resolve().parents[1] / "deploy" / "k3s"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LIVE = {
    "listener": {"poll_interval_seconds": 30},
    "llm": {
        "provider": "ollama",
        "base_url": "http://localhost:11434",
        "fallback_chain": ["ollama", "claude-cli", "anthropic"],
        "ollama_model_chain": ["m"],
        "claude_cli_allowed_tools": ["Bash"],
        "auto_pass_env_file": "/h/auto-pass.env",
        "anthropic_api_key_auto_pass_entry": "e/a",
        "openai_api_key_auto_pass_entry": "e/o",
        "timeout_seconds": 60,
    },
    "agent": {"enabled": True, "allowed_paths": ["/a", "/b"], "tools": ["shell", "read_file"]},
    "signal": {"enabled": True, "trusted_senders": ["+15550001"], "shock_relay_dir": "/h/s"},
    "gmail": {"enabled": True, "trusted_senders": ["me@example.com"], "shock_relay_dir": "/h/g"},
    "dispatch": {"allowed_commands": ["git status", "systemctl --user status *", "date"]},
}


def test_the_confined_config_drops_everything_the_pod_cannot_or_must_not_do():
    cfg = load("make_config").confine(LIVE)

    assert cfg["signal"]["enabled"] is False
    assert cfg["dispatch"]["allowed_commands"] == load("make_config").CONFINED_COMMANDS
    assert not any(c.split()[0].rstrip("*") in {"git", "systemctl", "journalctl"} for c in cfg["dispatch"]["allowed_commands"])
    assert cfg["llm"]["fallback_chain"] == ["anthropic", "openai"] == cfg["agent"]["fallback_chain"]
    for key in ("auto_pass_env_file", "anthropic_api_key_auto_pass_entry", "ollama_model_chain", "claude_cli_allowed_tools"):
        assert key not in cfg["llm"]
    assert cfg["agent"]["allowed_paths"] == ["/tmp"]
    assert cfg["gmail"]["shock_relay_dir"].startswith("/opt/shock-relay/")
    assert cfg["gmail"]["trusted_senders"] == ["me@example.com"], "who may command it is kept"
    assert LIVE["signal"]["enabled"] is True, "the live config is not modified"


def test_the_confined_config_is_valid_toml_that_round_trips():
    module = load("make_config")
    cfg = module.confine(LIVE)

    assert tomllib.loads(module.dumps(cfg)) == cfg


def test_the_gmail_config_carries_no_vault_entries_only_environment_names():
    live = {
        "keepass_profile": "p",
        "imap": {"host": "imap.gmail.com", "username_keepass_entry": "x#u", "password_keepass_entry": "x#p"},
        "smtp": {"password_keepass_entry": "x#s"},
        "paths": {"data_dir": "./d"},
    }

    out = load("make_secrets").gmail_config(live)

    text = yaml.safe_dump(out)
    assert "keepass" not in text and "x#" not in text
    assert out["imap"]["username_env"] == "GMAIL_IMAP_USERNAME"
    assert out["smtp"]["password_env"] == "GMAIL_IMAP_APP_PASSWORD"
    assert out["paths"]["data_dir"] == "/tmp/gmail-imap"


def docs(name):
    return list(yaml.safe_load_all((DEPLOY / "manifests" / name).read_text()))


def test_the_pod_runs_unprivileged_with_no_kubernetes_api_access():
    (deployment,) = docs("20-deployment.yaml")
    pod = deployment["spec"]["template"]["spec"]
    container = pod["containers"][0]

    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert deployment["spec"]["strategy"]["type"] == "Recreate", "never two pollers on one mailbox"
    assert "hostNetwork" not in pod and "hostPID" not in pod
    assert not any("hostPath" in v for v in pod["volumes"])


def test_the_namespace_enforces_the_restricted_pod_security_standard():
    (namespace,) = docs("00-namespace.yaml")

    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_the_network_policy_denies_by_default_and_names_every_destination():
    (policy,) = docs("30-network-policy.yaml")
    spec = policy["spec"]

    assert spec["ingressDeny"] == [{"fromEntities": ["all"]}]
    assert {"host", "kube-apiserver"} <= set(spec["egressDeny"][0]["toEntities"])
    allowed = [n["matchName"] for rule in spec["egress"] for n in rule.get("toFQDNs", [])]
    assert sorted(allowed) == ["api.anthropic.com", "api.openai.com", "imap.gmail.com", "smtp.gmail.com"]
    for rule in spec["egress"]:
        assert "toCIDR" not in rule and "toEntities" not in rule, "no address-range or entity allows"
        assert "toFQDNs" in rule or "toEndpoints" in rule
        for port in (p for tp in rule.get("toPorts", []) for p in tp["ports"]):
            assert port["port"] in {"53", "443", "465", "587", "993"}
