#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
grep -q 'FreePBX was not detected' "$ROOT/install.sh"
grep -q 'matching FreePBX/Sangoma' "$ROOT/install.sh"
grep -q 'make install DESTDIR=' "$ROOT/install.sh"
grep -q 'TOMOS-SCCP MANAGED BLOCK' "$ROOT/scripts/manage-modules-conf.py"
grep -q 'chan_sccp.so' "$ROOT/scripts/tomos-sccp-doctor.sh"
grep -q 'chan_skinny.so' "$ROOT/scripts/manage-modules-conf.py"
grep -q 'nortien/sccp_manager.git' "$ROOT/install-manager.sh"
grep -q 'install-manager.sh' "$ROOT/install-stack.sh"
echo "Installer static checks passed."
