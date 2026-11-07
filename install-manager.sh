#!/usr/bin/env bash
# Install the unmodified FreePBX 17 SCCP Manager companion from its upstream repo.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
command -v fwconsole >/dev/null 2>&1 || { echo "FreePBX fwconsole was not found." >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "git is required." >&2; exit 1; }
command -v asterisk >/dev/null 2>&1 || { echo "Asterisk was not found." >&2; exit 1; }

if ! asterisk -rx 'module show like chan_sccp.so' 2>/dev/null | grep -Eq 'chan_sccp\.so[[:space:]]'; then
  echo "chan_sccp.so is not loaded. Run install.sh first; manager installation stopped." >&2
  exit 1
fi

MODULE_PATH="/var/www/html/admin/modules/sccp_manager"
MODULE_REPO="https://github.com/nortien/sccp_manager.git"
MODULE_BRANCH="stable"

export DEBIAN_FRONTEND=noninteractive
if ! php -m 2>/dev/null | grep -Eiq '^zip$'; then
  apt-get update
  apt-get install -y php-zip
fi

# Enable an already-installed TFTP service, but do not invent a TFTP root or
# replace an administrator's existing service configuration.
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^tftp\.socket'; then
  systemctl enable --now tftp.socket
elif [[ -f /etc/xinetd.d/tftpd ]]; then
  sed -i 's/disable[[:space:]]*=[[:space:]]*yes/disable         = no/' /etc/xinetd.d/tftpd
  systemctl restart xinetd
else
  echo "[WARN] No preconfigured TFTP service was found. The GUI module can install, but Cisco phones will need a working TFTP service before provisioning."
fi

if [[ -d "$MODULE_PATH" ]]; then
  if [[ ! -d "$MODULE_PATH/.git" ]]; then
    echo "Existing non-Git SCCP Manager installation found at $MODULE_PATH. It was left untouched; update it through FreePBX Module Admin." >&2
    exit 1
  fi
  REMOTE="$(git -C "$MODULE_PATH" remote get-url origin 2>/dev/null || true)"
  case "$REMOTE" in
    https://github.com/nortien/sccp_manager.git|https://github.com/nortien/sccp_manager|git@github.com:nortien/sccp_manager.git) ;;
    *) echo "Existing SCCP Manager checkout has an unexpected origin ($REMOTE); refusing to replace it." >&2; exit 1 ;;
  esac
  git -C "$MODULE_PATH" fetch --depth=1 origin "$MODULE_BRANCH"
  git -C "$MODULE_PATH" checkout -B "$MODULE_BRANCH" FETCH_HEAD
else
  install -d -m 0755 "$(dirname "$MODULE_PATH")"
  git clone --depth=1 --branch "$MODULE_BRANCH" "$MODULE_REPO" "$MODULE_PATH"
fi

fwconsole chown
fwconsole ma install sccp_manager
fwconsole reload

echo "SCCP Manager installed. In FreePBX, open SCCP Connectivity to configure server settings, phones, lines and buttons."
echo "Before connecting phones, configure a secure device allow-list, TFTP root, DHCP option 150 and phone firmware."
