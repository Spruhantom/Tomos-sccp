#!/usr/bin/env bash
# One-command TomOS SCCP driver installer.
# Installs the FreePBX GUI manager by default; set TOMOS_SCCP_INSTALL_MANAGER=0 to skip.
set -Eeuo pipefail
REPO_RAW="https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main"
[[ $EUID -eq 0 ]] || { echo "Run as root: curl -fsSL $REPO_RAW/install-stack.sh | sudo bash" >&2; exit 1; }
TMP="$(mktemp -d /tmp/tomos-sccp-stack.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$REPO_RAW/install.sh" -o "$TMP/install.sh"
bash "$TMP/install.sh"
MANAGER_ENABLED="${TOMOS_SCCP_INSTALL_MANAGER:-1}"
case "$MANAGER_ENABLED" in
  1|true|yes) ;;
  0|false|no) MANAGER_ENABLED=0 ;;
  *) echo "Invalid TOMOS_SCCP_INSTALL_MANAGER value: use 1 or 0." >&2; exit 2 ;;
esac
if [[ "$MANAGER_ENABLED" != "0" ]]; then
  curl -fsSL "$REPO_RAW/install-manager.sh" -o "$TMP/install-manager.sh"
  bash "$TMP/install-manager.sh"
fi
if [[ "$MANAGER_ENABLED" != "0" ]]; then
  echo "TomOS SCCP driver and FreePBX SCCP Manager GUI installed."
  echo "Open FreePBX > SCCP Connectivity to manage phones and provisioning."
else
  echo "TomOS SCCP driver installed; GUI manager installation was explicitly skipped."
fi
