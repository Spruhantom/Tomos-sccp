#!/usr/bin/env bash
# Install the native TomOS SCCP FreePBX module backed by the CLI inventory DB.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
command -v fwconsole >/dev/null 2>&1 || { echo "FreePBX fwconsole was not found." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required." >&2; exit 1; }
command -v asterisk >/dev/null 2>&1 || { echo "Asterisk was not found." >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required." >&2; exit 1; }

if ! asterisk -rx 'module show like chan_sccp.so' 2>/dev/null | grep -Eq 'chan_sccp\\.so[[:space:]]'; then
  echo "chan_sccp.so is not loaded. Run install.sh first; GUI installation stopped." >&2
  exit 1
fi

MODULE_PATH="/var/www/html/admin/modules/tomos_sccp"
MODULE_REPO="https://github.com/Spruhantom/Tomos-sccp.git"
TMP="$(mktemp -d /tmp/tomos-sccp-gui.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

git clone --depth=1 "$MODULE_REPO" "$TMP/source"
SOURCE_MODULE="$TMP/source/freepbx-module/tomos_sccp"
[[ -f "$SOURCE_MODULE/module.xml" && -f "$SOURCE_MODULE/page.tomos_sccp.php" ]] || {
  echo "Native TomOS FreePBX module files are missing from the repository." >&2
  exit 1
}

install -d -m 0755 "$(dirname "$MODULE_PATH")"
if [[ -e "$MODULE_PATH" && ! -f "$MODULE_PATH/module.xml" ]]; then
  echo "Refusing to replace unexpected content at $MODULE_PATH." >&2
  exit 1
fi
install -d -m 0755 "$MODULE_PATH"
install -m 0644 "$SOURCE_MODULE/module.xml" "$MODULE_PATH/module.xml"
install -m 0644 "$SOURCE_MODULE/page.tomos_sccp.php" "$MODULE_PATH/page.tomos_sccp.php"

# Initialise/migrate the one shared database. The manager sets group access
# for the FreePBX asterisk account while keeping the directory non-world-readable.
/usr/local/libexec/tomos-sccp/tomos-sccp-manager.py init
chown -R asterisk:asterisk "$MODULE_PATH"
fwconsole chown
fwconsole ma install tomos_sccp
fwconsole reload

echo "TomOS SCCP Manager installed. Open FreePBX > TomOS SCCP."
echo "The web page and CLI now use /var/lib/tomos-sccp/provisioning.db."
