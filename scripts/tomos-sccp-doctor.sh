#!/usr/bin/env bash
# Read-only diagnostics for TomOS SCCP / FreePBX 17.
set -uo pipefail
ASTERISK_BIN="$(command -v asterisk || true)"
MODULES_CONF="/etc/asterisk/modules.conf"
FAILURES=0
pass() { printf '[ OK ] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
if [[ -z "$ASTERISK_BIN" ]]; then fail "asterisk command is unavailable"; exit 2; fi
VERSION="$("$ASTERISK_BIN" -rx 'core show version' 2>/dev/null | sed -nE 's/^Asterisk ([0-9]+\.[0-9]+[^ ]*).*/\1/p' | head -n1)"
[[ -n "$VERSION" ]] && pass "Asterisk responds: $VERSION" || fail "Asterisk CLI is unavailable"
SETTINGS="$("$ASTERISK_BIN" -rx 'core show settings' 2>/dev/null || true)"
MODULE_DIR="$(sed -nE 's/^[[:space:]]*Module directory:[[:space:]]*(.*)$/\1/p' <<<"$SETTINGS" | head -n1)"
[[ -n "$MODULE_DIR" && -d "$MODULE_DIR" ]] && pass "Module directory: $MODULE_DIR" || fail "Cannot determine module directory"
[[ -n "$MODULE_DIR" && -f "$MODULE_DIR/chan_sccp.so" ]] && pass "chan_sccp.so exists" || fail "chan_sccp.so is missing"
LOADED="$("$ASTERISK_BIN" -rx 'module show like chan_sccp.so' 2>/dev/null || true)"
grep -Eq 'chan_sccp\.so[[:space:]]' <<<"$LOADED" && pass "chan_sccp.so is loaded" || fail "chan_sccp.so is not loaded"
if [[ -r "$MODULES_CONF" ]] && grep -Fq '; BEGIN TOMOS-SCCP MANAGED BLOCK' "$MODULES_CONF" && grep -Eq '^[[:space:]]*noload[[:space:]]*=>[[:space:]]*chan_skinny\.so' "$MODULES_CONF" && grep -Eq '^[[:space:]]*load[[:space:]]*=>[[:space:]]*chan_sccp\.so' "$MODULES_CONF"; then pass "Persistent module directives are present"; else warn "Persistent module directives are missing"; fi
for dependency in app_voicemail.so bridge_simple.so bridge_native_rtp.so bridge_softmix.so bridge_holding.so res_stasis.so res_stasis_device_state.so; do
  result="$("$ASTERISK_BIN" -rx "module show like $dependency" 2>/dev/null || true)"
  grep -Eq "${dependency}[[:space:]]" <<<"$result" && pass "Dependency loaded: $dependency" || warn "Dependency not reported as loaded: $dependency"
done
if (( FAILURES > 0 )); then printf '\nFound %d blocking issue(s). Review: journalctl -u asterisk -n 100\n' "$FAILURES"; exit 1; fi
printf '\nDiagnostics completed. Review warnings before production use.\n'
