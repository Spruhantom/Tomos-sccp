#!/usr/bin/env bash
# TomOS SCCP installer for FreePBX 17 / Debian 12.
set -Eeuo pipefail

PROJECT="TomOS SCCP"
REPO_RAW="https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main"
UPSTREAM_URL="https://github.com/nortien/chan-sccp.git"
UPSTREAM_REF="${TOMOS_SCCP_REF:-stable}"
WORKDIR="/usr/src/tomos-sccp"
ASTERISK_ETC="/etc/asterisk"
MODULES_CONF="${ASTERISK_ETC}/modules.conf"
BACKUP_DIR="/var/backups/tomos-sccp/$(date +%Y%m%d-%H%M%S)"
HELPERS="/usr/local/libexec/tomos-sccp"

log() { printf '\n[%s] %s\n' "$PROJECT" "$*"; }
die() { printf '\n[%s] ERROR: %s\n' "$PROJECT" "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: curl -fsSL $REPO_RAW/install.sh | sudo bash"
command -v apt-get >/dev/null 2>&1 || die "This installer requires Debian 12 with APT."
[[ -r /etc/os-release ]] || die "Cannot identify the operating system."
# shellcheck disable=SC1091
. /etc/os-release
[[ "${ID:-}" == debian && "${VERSION_ID:-}" == 12 ]] || die "Supported platform: Debian 12 / FreePBX 17. Detected ${PRETTY_NAME:-unknown}."
command -v fwconsole >/dev/null 2>&1 || die "FreePBX was not detected (fwconsole is missing)."
command -v asterisk >/dev/null 2>&1 || die "Asterisk is not installed."
command -v python3 >/dev/null 2>&1 || die "python3 is required."
[[ "$UPSTREAM_REF" =~ ^[A-Za-z0-9._/-]+$ && "$UPSTREAM_REF" != *..* ]] || die "Invalid TOMOS_SCCP_REF."

ASTERISK_VERSION="$(asterisk -rx 'core show version' 2>/dev/null | sed -nE 's/^Asterisk ([0-9]+)\..*/\1/p' | head -n1)"
[[ -n "$ASTERISK_VERSION" ]] || die "Could not read the running Asterisk version."
(( ASTERISK_VERSION >= 18 && ASTERISK_VERSION <= 23 )) || die "Asterisk $ASTERISK_VERSION is outside the supported major range (18–23). No changes made."
MODULE_DIR="$(asterisk -rx 'core show settings' 2>/dev/null | sed -nE 's/^[[:space:]]*Module directory:[[:space:]]*(.*)$/\1/p' | head -n1)"
[[ -n "$MODULE_DIR" && -d "$MODULE_DIR" ]] || die "Could not determine Asterisk's active module directory."
[[ -f /usr/include/asterisk.h && -f /usr/include/asterisk/module.h ]] || die "Matching FreePBX/Sangoma Asterisk development headers are missing. Install the vendor-matched Asterisk $ASTERISK_VERSION development package; generic Debian headers may not match your PBX."

log "Detected FreePBX 17 with Asterisk $ASTERISK_VERSION."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends build-essential git autoconf automake libtool pkg-config gettext libxml2-dev libxslt1-dev libssl-dev uuid-dev curl python3
git check-ref-format --branch "$UPSTREAM_REF" >/dev/null 2>&1 || die "Invalid upstream Git ref."

install -d -m 0755 "$WORKDIR" "$BACKUP_DIR" "$HELPERS"
curl -fsSL "$REPO_RAW/scripts/manage-modules-conf.py" -o "$HELPERS/manage-modules-conf.py"
curl -fsSL "$REPO_RAW/scripts/tomos-sccp-doctor.sh" -o "$HELPERS/tomos-sccp-doctor.sh"
chmod 0755 "$HELPERS/tomos-sccp-doctor.sh"
[[ ! -f "$MODULE_DIR/chan_sccp.so" ]] || cp -a "$MODULE_DIR/chan_sccp.so" "$BACKUP_DIR/chan_sccp.so.previous"
[[ ! -f "$MODULES_CONF" ]] || cp -a "$MODULES_CONF" "$BACKUP_DIR/modules.conf.original"

log "Fetching upstream chan-sccp ($UPSTREAM_REF)."
if [[ -d "$WORKDIR/chan-sccp/.git" ]]; then
  git -C "$WORKDIR/chan-sccp" fetch --depth=1 origin "$UPSTREAM_REF"
  git -C "$WORKDIR/chan-sccp" checkout -B "$UPSTREAM_REF" FETCH_HEAD
else
  rm -rf "$WORKDIR/chan-sccp"
  git clone --depth=1 --branch "$UPSTREAM_REF" "$UPSTREAM_URL" "$WORKDIR/chan-sccp"
fi
cd "$WORKDIR/chan-sccp"
[[ -x ./configure ]] || die "Upstream configure script is missing."
log "Building against the installed Asterisk headers."
./configure
make -j"$(nproc)"
STAGE="$(mktemp -d /tmp/tomos-sccp-stage.XXXXXX)"
trap 'rm -rf "${STAGE:-}"' EXIT
make install DESTDIR="$STAGE"
BUILT_MODULE="$(find "$STAGE" -type f -name chan_sccp.so -print -quit)"
[[ -n "$BUILT_MODULE" ]] || die "Staged build did not produce chan_sccp.so."

for dependency in app_voicemail.so bridge_simple.so bridge_native_rtp.so bridge_softmix.so bridge_holding.so res_stasis.so res_stasis_device_state.so; do
  status="$(asterisk -rx "module show like $dependency" 2>/dev/null || true)"
  if ! grep -Eq "${dependency}[[:space:]]" <<<"$status"; then
    asterisk -rx "module load $dependency" >/dev/null 2>&1 || die "Required Asterisk dependency $dependency could not be loaded; active SCCP module was not replaced."
  fi
done

# Unload the old driver before replacing its file. If it is busy, stop here
# with the existing module file and FreePBX configuration untouched.
if asterisk -rx 'module show like chan_sccp.so' 2>/dev/null | grep -Eq 'chan_sccp\.so[[:space:]]'; then
  asterisk -rx 'module unload chan_sccp.so' >/dev/null 2>&1 || die "Existing chan_sccp module is busy. End active calls or schedule a maintenance restart; no file was replaced."
fi

log "Installing the staged channel driver."
if ! install -o asterisk -g asterisk -m 0644 "$BUILT_MODULE" "$MODULE_DIR/chan_sccp.so"; then
  [[ ! -f "$BACKUP_DIR/chan_sccp.so.previous" ]] || asterisk -rx 'module load chan_sccp.so' >/dev/null 2>&1 || true
  die "Could not install the new module. The previous module file was retained where possible."
fi
if ! python3 "$HELPERS/manage-modules-conf.py" "$MODULES_CONF"; then
  if [[ -f "$BACKUP_DIR/chan_sccp.so.previous" ]]; then
    cp -a "$BACKUP_DIR/chan_sccp.so.previous" "$MODULE_DIR/chan_sccp.so"
    asterisk -rx 'module load chan_sccp.so' >/dev/null 2>&1 || true
  fi
  die "Could not safely update modules.conf. Previous driver was restored where available."
fi

asterisk -rx 'module unload chan_skinny.so' >/dev/null 2>&1 || true
if ! asterisk -rx 'module load chan_sccp.so' >/dev/null 2>&1; then
  if [[ -f "$BACKUP_DIR/chan_sccp.so.previous" ]]; then
    cp -a "$BACKUP_DIR/chan_sccp.so.previous" "$MODULE_DIR/chan_sccp.so"
    asterisk -rx 'module load chan_sccp.so' >/dev/null 2>&1 || true
  else
    rm -f "$MODULE_DIR/chan_sccp.so"
  fi
  if [[ -f "$BACKUP_DIR/modules.conf.original" ]]; then cp -a "$BACKUP_DIR/modules.conf.original" "$MODULES_CONF"; else rm -f "$MODULES_CONF"; fi
  asterisk -rx 'module load chan_skinny.so' >/dev/null 2>&1 || true
  die "Asterisk failed to load chan_sccp.so; previous module/configuration were restored where available. Check journalctl -u asterisk."
fi

UPSTREAM_COMMIT="$(git rev-parse HEAD)"
printf 'installed_at=%s\nasterisk_major=%s\nupstream_ref=%s\nupstream_commit=%s\n' "$(date -Is)" "$ASTERISK_VERSION" "$UPSTREAM_REF" "$UPSTREAM_COMMIT" > /var/lib/asterisk/tomos-sccp-install.info
chown asterisk:asterisk /var/lib/asterisk/tomos-sccp-install.info
log "Installation complete. Driver loaded; no phone credentials or extension configuration were changed."
printf '\nDiagnostics: sudo %s/tomos-sccp-doctor.sh\n' "$HELPERS"
printf 'Backup: %s\n' "$BACKUP_DIR"
printf 'Next: configure /etc/asterisk/chan_sccp.conf and verify FreePBX Admin → Asterisk Modules.\n'
