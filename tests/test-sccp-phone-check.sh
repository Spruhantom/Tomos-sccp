#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/tomos-sccp-phone-check.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cat > "$TMP/asterisk" <<'MOCK'
#!/usr/bin/env bash
case "$2" in
  "core show version") echo "Asterisk 20.7.0";;
  "module show like chan_sccp.so") echo "chan_sccp.so  Running";;
  "sccp show devices") echo "SEP001122AABBCC Registered";;
  "sccp show lines") echo "1000 In use";;
  *) echo "unexpected command: $2" >&2; exit 1;;
esac
MOCK
chmod +x "$TMP/asterisk"
output="$(ASTERISK_BIN="$TMP/asterisk" "$SCRIPT" --mac 00:11:22:AA:BB:CC --extension 1000)"
grep -q 'Asterisk 20.7.0' <<<"$output"
grep -q 'chan_sccp.so is loaded' <<<"$output"
grep -q 'SEP001122AABBCC Registered' <<<"$output"
grep -q '1000 In use' <<<"$output"
grep -q 'MAC: 001122AABBCC' <<<"$output"
if ASTERISK_BIN="$TMP/asterisk" "$SCRIPT" --mac invalid >/dev/null 2>&1; then
  echo "invalid MAC was accepted" >&2
  exit 1
fi
echo "TomOS SCCP phone-check tests passed."
