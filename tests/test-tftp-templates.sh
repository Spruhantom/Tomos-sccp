#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/source" "$TMP/tftp/templates"
printf 'new template\n' > "$TMP/source/SEP-test-template.xml"
printf 'admin version\n' > "$TMP/tftp/templates/SEP-test-template.xml"
printf 'second template\n' > "$TMP/source/XMLDefault.cnf.xml"
TOMOS_SCCP_TEMPLATE_SOURCE="$TMP/source" bash "$ROOT/scripts/tomos-sccp-install-tftp-templates.sh" --tftp-root "$TMP/tftp"
[[ "$(cat "$TMP/tftp/templates/SEP-test-template.xml")" == "admin version" ]]
[[ "$(cat "$TMP/tftp/templates/XMLDefault.cnf.xml")" == "second template" ]]
echo "TFTP template deployment tests passed."
