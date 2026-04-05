#!/usr/bin/env bash
# scripts/install_listener_systemd.sh ��� render and install the crew-chief listener
# as a user-level systemd service via the shared clockwork scheduler utility.
#
# Usage:
#   scripts/install_listener_systemd.sh [options]
#
# The service is enabled and started by default.  Pass --render-only to
# write the unit file only and skip daemon-reload / enable / start.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_PATH="${REPO_ROOT}/config/clockwork/crew-chief-listener.toml.template"
UNIT_TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
CLOCKWORK_REPO_DEFAULT="${REPO_ROOT}/../clockwork"
CLOCKWORK_REPO="${CLOCKWORK_REPO:-${CLOCKWORK_REPO_DEFAULT}}"
RENDER_ONLY=0

usage() {
  cat <<EOF
Usage: install_listener_systemd.sh [options]

Render the crew-chief listener as a user-level systemd service via clockwork
and enable + start it by default.

Options:
  --render-only         Write the unit file only; skip daemon-reload/enable/start.
  --unit-dir DIR        Override the target unit directory.
  --clockwork-repo PATH Override the sibling clockwork repo path fallback.
  --help                Show this help text.
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|]/\\&/g'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --render-only)
      RENDER_ONLY=1
      shift
      ;;
    --unit-dir)
      UNIT_TARGET_DIR="$2"
      shift 2
      ;;
    --clockwork-repo)
      CLOCKWORK_REPO="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

command -v python3 >/dev/null 2>&1 || fail "python3 not found"
[[ -f "${TEMPLATE_PATH}" ]] || fail "missing template: ${TEMPLATE_PATH}"

# Verify the listener config exists before installing the service.
LISTENER_CONFIG="${REPO_ROOT}/config/listener/config.toml"
if [[ ! -f "${LISTENER_CONFIG}" && "${RENDER_ONLY}" -eq 0 ]]; then
  fail "listener config not found: ${LISTENER_CONFIG}
Copy config/listener/config.toml.example to config/listener/config.toml and configure it first."
fi

# Resolve clockwork command.
if command -v clockwork >/dev/null 2>&1; then
  CLOCKWORK_CMD=(clockwork)
else
  [[ -d "${CLOCKWORK_REPO}/src/clockwork" ]] || \
    fail "clockwork not found at ${CLOCKWORK_REPO} and not on PATH"
  export PYTHONPATH="${CLOCKWORK_REPO}/src${PYTHONPATH:+:${PYTHONPATH}}"
  CLOCKWORK_CMD=(python3 -m clockwork)
fi

# Substitute placeholders into a temp manifest.
# Use XDG_RUNTIME_DIR (e.g. /run/user/1000) if /tmp is unavailable.
_TMPDIR="${TMPDIR:-${XDG_RUNTIME_DIR:-${HOME}/.cache/crew-chief}}"
mkdir -p "${_TMPDIR}"
TMP_MANIFEST="$(mktemp -p "${_TMPDIR}")"
trap 'rm -f "${TMP_MANIFEST}"' EXIT

sed \
  -e "s|__REPO_ROOT__|$(escape_sed_replacement "${REPO_ROOT}")|g" \
  "${TEMPLATE_PATH}" > "${TMP_MANIFEST}"

"${CLOCKWORK_CMD[@]}" install \
  --manifest "${TMP_MANIFEST}" \
  --target systemd-user \
  --unit-dir "${UNIT_TARGET_DIR}"

if (( RENDER_ONLY == 1 )); then
  exit 0
fi

# Enable lingering so the user systemd instance starts on boot (no login needed).
if ! loginctl show-user "$(id -un)" 2>/dev/null | grep -q "^Linger=yes"; then
  echo "Enabling linger for $(id -un) (allows user services to start at boot) ..."
  loginctl enable-linger "$(id -un)"
fi

systemctl --user daemon-reload
systemctl --user enable --now crew-chief-listener.service
echo ""
systemctl --user status crew-chief-listener.service --no-pager || true
