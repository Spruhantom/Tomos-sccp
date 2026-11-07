#!/usr/bin/env bash
# One-command TomOS SCCP driver installer.
# The separate GUI manager is optional until compatibility is validated.
set -Eeuo pipefail
REPO_RAW="https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main"
[[ $EUID -eq 0 ]] || { echo "Run as root: curl -fsSL $REPO_RAW/install-stack.sh | sudo bash" >&2; exit 1; }
TMP="$(mktemp -d /tmp/tomos-sccp-stack.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$REPO_RAW/install.sh" -o "$TMP/install.sh"
bash "$TMP/install.sh"
if [[ "${TOMOS_SCCP_INSTALL_MANAGER:-0}" == "1" ]]; then
  curl -fsSL "$REPO_RAW/install-manager.sh" -o "$TMP/install-manager.sh"
  bash "$TMP/install-manager.sh"
fi
echo "TomOS SCCP driver installed. GUI manager installation is optional and not enabled by default."
