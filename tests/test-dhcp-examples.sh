#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DNSMASQ="$ROOT/examples/dhcp/dnsmasq.conf"
ISC="$ROOT/examples/dhcp/isc-dhcpd.conf"

test -s "$DNSMASQ"
test -s "$ISC"
grep -Eq '^dhcp-option=150,([0-9]{1,3}\.){3}[0-9]{1,3}$' "$DNSMASQ"
grep -q '^interface=eth1$' "$DNSMASQ"
grep -q '^option cisco-tftp-servers code 150 = array of ip-address;$' "$ISC"
grep -q '^  option cisco-tftp-servers 192\.168\.10\.5;$' "$ISC"
grep -q 'ISC DHCP is end-of-life' "$ISC"
echo "Cisco DHCP example checks passed."
