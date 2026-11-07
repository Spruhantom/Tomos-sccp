#!/usr/bin/env bash
# Read-only live PBX snapshot for Cisco SCCP handset verification.
set -uo pipefail

MAC=""
EXTENSION=""
ASTERISK_BIN="${ASTERISK_BIN:-$(command -v asterisk || true)}"
usage() {
  cat <<'EOF'
Usage: tomos-sccp-phone-check.sh [--mac 001122AABBCC] [--extension 1000]

Collects read-only Asterisk/SCCP status for a physical handset test.
It does not change configuration, reload Asterisk, or place calls.
EOF
}
fail() { printf '[FAIL] %s\n' "$*" >&2; }
while (($#)); do
  case "$1" in
    --mac)
      (($# >= 2)) || { usage >&2; exit 2; }
      MAC="${2//:/}"; MAC="${MAC//-/}"; MAC="${MAC^^}"
      [[ "$MAC" =~ ^[0-9A-F]{12}$ ]] || { fail "invalid --mac"; exit 2; }
      shift 2 ;;
    --extension)
      (($# >= 2)) || { usage >&2; exit 2; }
      EXTENSION="$2"
      [[ "$EXTENSION" =~ ^[0-9]{1,20}$ ]] || { fail "invalid --extension"; exit 2; }
      shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown argument: $1"; usage >&2; exit 2 ;;
  esac
done

[[ -n "$ASTERISK_BIN" && -x "$ASTERISK_BIN" ]] || { fail "asterisk executable not found"; exit 2; }
run_cli() {
  local command="$1" output
  printf '\n--- asterisk -rx %q ---\n' "$command"
  output="$("$ASTERISK_BIN" -rx "$command" 2>&1)"
  local status=$?
  printf '%s\n' "$output"
  if (( status != 0 )); then
    fail "Asterisk CLI command failed: $command"
    return 1
  fi
}

version="$("$ASTERISK_BIN" -rx 'core show version' 2>&1)"
status=$?
if (( status != 0 )) || [[ ! "$version" =~ Asterisk[[:space:]] ]]; then
  fail "Asterisk CLI is not responding"
  printf '%s\n' "$version"
  exit 1
fi
printf '[ OK ] %s\n' "$version"

modules="$("$ASTERISK_BIN" -rx 'module show like chan_sccp.so' 2>&1)"
status=$?
if (( status != 0 )) || ! grep -Eq 'chan_sccp\.so[[:space:]]' <<<"$modules"; then
  fail "chan_sccp.so is not reported as loaded"
  printf '%s\n' "$modules"
  exit 1
fi
printf '[ OK ] chan_sccp.so is loaded\n'

run_cli 'sccp show devices' || exit 1
run_cli 'sccp show lines' || exit 1
printf '\n--- Expected handset reference ---\n'
[[ -z "$MAC" ]] || printf 'MAC: %s (compare with the device listing above)\n' "$MAC"
[[ -z "$EXTENSION" ]] || printf 'Extension: %s (compare with the line listing above)\n' "$EXTENSION"
printf '\n--- Recent Asterisk service log (last 80 lines) ---\n'
if command -v journalctl >/dev/null 2>&1; then
  journalctl -u asterisk -n 80 --no-pager 2>&1 || true
else
  printf 'journalctl is unavailable; inspect the configured Asterisk log files.\n'
fi
printf '\nSnapshot complete. Confirm device state, line association and registration from the output; then perform real inbound/outbound and two-way-audio tests.\n'
