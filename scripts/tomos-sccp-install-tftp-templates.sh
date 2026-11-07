#!/usr/bin/env bash
# Copy upstream Cisco TFTP templates into an explicitly selected TFTP root.
set -Eeuo pipefail
SOURCE="${TOMOS_SCCP_TEMPLATE_SOURCE:-/usr/share/tomos-sccp/tftp-templates}"
usage() { echo "Usage: tomos-sccp-install-tftp-templates.sh --tftp-root PATH"; }
ROOT=""
while (($#)); do
  case "$1" in
    --tftp-root) (($# >= 2)) || { usage >&2; exit 2; }; ROOT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[[ -n "$ROOT" ]] || { usage >&2; exit 2; }
[[ -d "$SOURCE" ]] || { echo "Templates not found at $SOURCE. Reinstall TomOS SCCP first." >&2; exit 1; }
case "$ROOT" in /|/etc|/usr|/var|/home) echo "Refusing unsafe TFTP root: $ROOT" >&2; exit 1;; esac
install -d -m 0755 "$ROOT/templates"
COPIED=0
SKIPPED=0
while IFS= read -r -d '' file; do
  target="$ROOT/templates/$(basename "$file")"
  if [[ -e "$target" ]]; then
    echo "[SKIP] Existing file preserved: $target"
    SKIPPED=$((SKIPPED + 1))
  else
    install -m 0644 "$file" "$target"
    echo "[COPY] $target"
    COPIED=$((COPIED + 1))
  fi
done < <(find "$SOURCE" -maxdepth 1 -type f -print0)
echo "Finished: $COPIED copied, $SKIPPED existing file(s) preserved."
