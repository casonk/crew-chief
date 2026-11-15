"""deploy/deploy.sh: one setting chooses dev, host or k3s, and only k3s may touch a cluster.

The script runs against stub commands that record every call, so nothing here needs systemd, podman or a
cluster, which is the point: a developer without K3s must be able to run and test the listener.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DEPLOY = REPO / "deploy" / "deploy.sh"
K3S_STEPS = ["build-image.sh", "apply.sh", "verify.sh"]
UNIT = "crew-chief-listener.service"


def _stub(path: Path, log: Path, name: str, body: str = "") -> None:
    path.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> "{log}"\n{body}\n')
    path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    """A PATH of recording stubs, a stub k3s directory, and a private state folder."""
    bin_dir, k3s, log = tmp_path / "bin", tmp_path / "k3s", tmp_path / "calls.log"
    bin_dir.mkdir()
    k3s.mkdir()
    for name, body in {
        "kubectl": "exit 99",
        "podman": "exit 99",
        "curl": "exit 22",
        "systemctl": (
            'case "$*" in *is-active*) echo inactive; exit 3 ;; *is-enabled*) echo disabled; exit 1 ;; esac'
        ),
    }.items():
        _stub(bin_dir / name, log, name, body)
    for step in K3S_STEPS:
        _stub(k3s / step, log, step)
    shutil.copy(REPO / "deploy" / "k3s" / "env_value.py", k3s / "env_value.py")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CREW_CHIEF_K3S_DIR": str(k3s),
        "CREW_CHIEF_DEPLOY_CONFIG": str(tmp_path / "deploy.local.env"),
        "XDG_STATE_HOME": str(tmp_path / "state"),
    }
    env.pop("CREW_CHIEF_DEPLOY_MODE", None)
    return env, log, tmp_path


def run(env, *args):
    return subprocess.run(
        ["bash", str(DEPLOY), *args], env=env, capture_output=True, text=True, timeout=60
    )


def calls(log: Path) -> list[str]:
    return log.read_text().splitlines() if log.exists() else []


def names(log: Path) -> list[str]:
    return [c.split()[0] for c in calls(log)]


def _systemd(tmp_path, *, installed=True, active=False):
    """Make the systemctl stub describe a host listener that is (not) installed and (not) running."""
    log = tmp_path / "calls.log"
    body = (
        'case "$*" in\n'
        f'  *" cat "*) exit {0 if installed else 1} ;;\n'
        f"  *is-active*) {'echo active; exit 0' if active else 'echo inactive; exit 3'} ;;\n"
        "  *is-enabled*) echo disabled; exit 1 ;;\n"
        "esac"
    )
    _stub(tmp_path / "bin" / "systemctl", log, "systemctl", body)


def _cluster_ready(tmp_path):
    """Registry answers and kubectl succeeds."""
    log = tmp_path / "calls.log"
    _stub(tmp_path / "bin" / "curl", log, "curl")
    _stub(tmp_path / "bin" / "kubectl", log, "kubectl")


def _marker(tmp_path, value="k3s"):
    folder = tmp_path / "state" / "crew-chief"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "deploy-mode").write_text(value + "\n")
    return folder / "deploy-mode"


def test_the_default_mode_is_dev_so_a_fresh_checkout_needs_no_cluster(sandbox):
    env, _, _ = sandbox
    done = run(env, "mode")
    assert done.returncode == 0 and done.stdout.strip() == "dev (from default)"


def test_the_mode_comes_from_flag_then_environment_then_config_then_default(sandbox):
    env, _, tmp = sandbox
    config = tmp / "deploy.local.env"
    config.write_text('CREW_CHIEF_DEPLOY_MODE="host"\n')
    from_config = run(env, "mode").stdout
    # the quoted config value is read the way systemd would read it
    assert from_config.startswith("host (from ")
    assert str(config) in from_config
    assert (
        run({**env, "CREW_CHIEF_DEPLOY_MODE": "k3s"}, "mode").stdout.strip()
        == "k3s (from environment)"
    )
    flagged = run({**env, "CREW_CHIEF_DEPLOY_MODE": "k3s"}, "--mode", "dev", "mode")
    assert flagged.stdout.strip() == "dev (from --mode)"


def test_an_unknown_mode_is_an_error_not_a_silent_fallback(sandbox):
    env, _, tmp = sandbox
    done = run(env, "--mode", "docker", "mode")
    assert done.returncode == 2 and "unknown deployment mode" in done.stderr
    (tmp / "deploy.local.env").write_text("CREW_CHIEF_DEPLOY_MODE=cloud\n")
    done = run(env, "mode")
    assert done.returncode == 2 and str(tmp / "deploy.local.env") in done.stderr


def test_a_config_file_that_cannot_be_read_is_an_error_not_a_quiet_default(sandbox):
    env, _, tmp = sandbox
    config = tmp / "deploy.local.env"
    config.write_text("CREW_CHIEF_DEPLOY_MODE=host\n")
    config.chmod(0)
    if os.access(config, os.R_OK):  # running as root: permissions do not apply
        pytest.skip("cannot make the file unreadable")
    done = run(env, "mode")
    assert done.returncode != 0
    assert "dev (from default)" not in done.stdout


def test_a_missing_command_is_a_usage_error(sandbox):
    env, _, _ = sandbox
    assert run(env).returncode == 2


@pytest.mark.parametrize("command", ["mode", "status", "verify", "down"])
def test_dev_never_touches_kubectl_podman_or_systemd(sandbox, command):
    env, log, _ = sandbox
    run(env, "--mode", "dev", command)
    assert [n for n in names(log) if n in {"kubectl", "podman", "systemctl"}] == []


def test_dev_up_without_a_listener_config_says_what_to_copy(sandbox):
    env, log, tmp = sandbox
    done = run(
        {**env, "CREW_CHIEF_LISTENER_CONFIG": str(tmp / "missing.toml")}, "--mode", "dev", "up"
    )
    assert done.returncode == 1 and "config.toml.example" in done.stderr
    assert names(log) == []


def test_host_up_enables_the_unit_and_never_touches_kubectl_or_podman(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp)
    done = run(env, "--mode", "host", "up")
    assert done.returncode == 0, done.stderr
    assert f"systemctl --user enable --now {UNIT}" in calls(log)
    assert [n for n in names(log) if n in {"kubectl", "podman"}] == []


def test_host_up_without_the_unit_says_how_to_install_it_and_changes_nothing(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp, installed=False)
    done = run(env, "--mode", "host", "up")
    assert done.returncode == 1 and "not installed" in done.stderr and "Clockwork" in done.stderr
    assert f"systemctl --user enable --now {UNIT}" not in calls(log)


def test_host_down_disables_only_the_unit(sandbox):
    env, log, _ = sandbox
    run(env, "--mode", "host", "down")
    assert f"systemctl --user disable --now {UNIT}" in calls(log)
    assert [n for n in names(log) if n in {"kubectl", "podman"}] == []


def test_leaving_k3s_stops_the_pod_before_the_host_listener_starts(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp)
    _cluster_ready(tmp)
    marker = _marker(tmp)
    done = run(env, "--mode", "host", "up")
    assert done.returncode == 0, done.stderr
    seen = calls(log)
    scale = next(i for i, c in enumerate(seen) if c.startswith("kubectl") and "--replicas=0" in c)
    assert scale < seen.index(f"systemctl --user enable --now {UNIT}")
    assert not marker.exists()


def test_leaving_k3s_without_kubectl_refuses_rather_than_double_polling(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp)
    marker = _marker(tmp)
    done = run({**env, "KUBECTL": "definitely-not-installed"}, "--mode", "host", "up")
    assert done.returncode == 1 and "both will answer mail" in done.stderr
    assert f"systemctl --user enable --now {UNIT}" not in calls(log)
    assert marker.exists()


def test_k3s_refuses_without_kubectl_and_says_dev_and_host_do_not_need_it(sandbox):
    env, log, _ = sandbox
    done = run({**env, "KUBECTL": "definitely-not-installed"}, "--mode", "k3s", "up")
    assert done.returncode == 1
    assert (
        "k3s mode needs kubectl" in done.stderr and "dev and host modes need neither" in done.stderr
    )
    assert [n for n in names(log) if n in {"podman", "systemctl"} or n.endswith(".sh")] == []


def test_k3s_refuses_without_the_registry_and_stops_nothing(sandbox):
    env, log, _ = sandbox
    done = run(env, "--mode", "k3s", "up")  # kubectl and podman exist (stubs); the curl stub fails
    assert done.returncode == 1 and "in-cluster registry" in done.stderr
    assert [n for n in names(log) if n.endswith(".sh") or n == "systemctl"] == []


def test_k3s_up_stops_the_host_listener_before_anything_starts_and_records_the_hand_over(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp, active=True)
    _cluster_ready(tmp)
    done = run(env, "--mode", "k3s", "up")
    assert done.returncode == 0, done.stderr
    seen = calls(log)
    stop = seen.index(f"systemctl --user disable --now {UNIT}")
    steps = [n for n in names(log) if n.endswith(".sh")]
    assert steps == K3S_STEPS
    assert stop < seen.index("build-image.sh ")
    assert (tmp / "state" / "crew-chief" / "deploy-mode").read_text().strip() == "k3s"
    assert f"systemctl --user enable --now {UNIT}" not in seen


@pytest.mark.parametrize("failing", K3S_STEPS)
def test_a_failed_step_scales_the_pod_down_and_restores_the_host_listener(sandbox, failing):
    env, log, tmp = sandbox
    _systemd(tmp, active=True)
    _cluster_ready(tmp)
    _stub(tmp / "k3s" / failing, log, failing, "exit 1")
    done = run(env, "--mode", "k3s", "up")
    assert done.returncode != 0
    seen = calls(log)
    assert any(c.startswith("kubectl") and "--replicas=0" in c for c in seen)
    assert f"systemctl --user enable --now {UNIT}" in seen
    assert not (tmp / "state" / "crew-chief" / "deploy-mode").exists()


def test_a_failed_step_does_not_start_a_host_listener_that_was_not_running(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp, active=False)
    _cluster_ready(tmp)
    _stub(tmp / "k3s" / "verify.sh", log, "verify.sh", "exit 1")
    done = run(env, "--mode", "k3s", "up")
    assert done.returncode != 0
    assert f"systemctl --user enable --now {UNIT}" not in calls(log)


def test_k3s_down_is_host_up(sandbox):
    env, log, tmp = sandbox
    _systemd(tmp)
    _cluster_ready(tmp)
    _marker(tmp)
    done = run(env, "--mode", "k3s", "down")
    assert done.returncode == 0, done.stderr
    assert any("--replicas=0" in c for c in calls(log))


def test_the_image_build_refuses_uncommitted_source_unless_told_otherwise(tmp_path):
    repo = tmp_path / "repo"
    (repo / "deploy" / "k3s").mkdir(parents=True)
    (repo / "src").mkdir()
    shutil.copy(
        REPO / "deploy" / "k3s" / "build-image.sh", repo / "deploy" / "k3s" / "build-image.sh"
    )
    (repo / "deploy" / "k3s" / "Containerfile.listener").write_text("FROM scratch\n")
    (repo / "src" / "mod.py").write_text("x = 1\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-qm", "init"], check=True)
    (repo / "src" / "mod.py").write_text("x = 2\n")

    log = tmp_path / "calls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub(bin_dir / "podman", log, "podman")
    shock = tmp_path / "shock"
    (shock / "services" / "gmail-imap").mkdir(parents=True)
    _stub(repo / "deploy" / "k3s" / "push-image.sh", log, "push-image.sh")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SHOCK_RELAY_DIR": str(shock)}
    script = repo / "deploy" / "k3s" / "build-image.sh"

    refused = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True)
    assert refused.returncode == 1 and "uncommitted changes" in refused.stderr
    assert "podman" not in names(log)

    allowed = subprocess.run(
        ["bash", str(script)], env={**env, "ALLOW_DIRTY": "1"}, capture_output=True, text=True
    )
    assert allowed.returncode == 0, allowed.stderr
    assert "podman" in names(log)


def test_host_scripts_use_only_python_flags_that_exist_on_the_oldest_supported_python():
    # `python3 -P` is Python 3.11+; -I (isolated) exists everywhere and keeps the script directory off sys.path.
    # A line that runs inside the pod (kubectl exec, Python 3.12 image) may use -P.
    for path in (REPO / "deploy").rglob("*.sh"):
        for line in path.read_text().splitlines():
            if "python3 -P" in line:
                assert " exec " in line, f"{path.name}: {line.strip()}"


def test_the_local_config_is_gitignored_and_the_example_and_docs_cover_every_mode(sandbox):
    env, _, _ = sandbox
    assert "config/deploy.local.env" in (REPO / ".gitignore").read_text()
    example = REPO / "config" / "deploy.example.env"
    done = run({**env, "CREW_CHIEF_DEPLOY_CONFIG": str(example)}, "mode")
    assert done.returncode == 0 and done.stdout.startswith("dev (from ")
    docs = (REPO / "docs" / "deployment.md").read_text()
    for needle in (
        "`dev`",
        "`host`",
        "`k3s`",
        "Switching",
        "only the `k3s` mode needs a",
        "deploy/deploy.sh",
    ):
        assert needle in docs, needle
    assert "docs/deployment.md" in (REPO / "README.md").read_text()


def test_the_restore_trap_fires_for_failures_inside_functions():
    # Without `set -E` bash does not inherit an ERR trap into functions, so a failure inside a function skips the
    # restore. The portfolio's deployment-modes contract requires set -eEuo pipefail.
    assert "set -eEuo pipefail" in DEPLOY.read_text()
