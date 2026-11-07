#!/usr/bin/env python3
"""Tests for the native TomOS SCCP inventory manager."""
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/tomos-sccp-manager.py"


def run(db, *args, expected=0):
    result = subprocess.run([sys.executable, str(SCRIPT), "--database", str(db), *map(str, args)],
                            text=True, capture_output=True)
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    database = root / "state" / "phones.db"
    output = root / "generated"

    assert "database ready" in run(database, "init").stdout
    assert "cisco" in run(database, "vendor", "list").stdout
    assert "7940_7960" in run(database, "model", "list").stdout

    add_args = ("device", "add", "--mac", "00:11:22:33:44:55", "--vendor", "cisco",
                "--model", "7960", "--template-family", "7940_7960",
                "--extension", "1000", "--description", "Front desk",
                "--label", "Front desk", "--cid-name", "Front Desk",
                "--dhcp-address", "192.168.10.50")
    assert "Added cisco 7960" in run(database, *add_args).stdout
    assert "Front desk" in run(database, "device", "list").stdout
    run(database, "device", "update", "--mac", "001122334455", "--description", "Main reception")
    details = run(database, "device", "show", "--mac", "001122334455").stdout
    assert "description: Main reception" in details
    run(database, "device", "update", "--mac", "001122334455", "--context", "bad\\n[general]", expected=2)
    assert "template_family: 7940_7960" in details
    assert "extension: 1000" in details

    # Reservation exports are generated only on request and never modify DHCP.
    dnsmasq_export = root / "exports" / "tomos-phones.conf"
    exported = run(database, "dhcp-export", "--format", "dnsmasq",
                   "--output", dnsmasq_export)
    assert "active DHCP was not changed" in exported.stdout
    dnsmasq_text = dnsmasq_export.read_text(encoding="utf-8")
    assert "dhcp-host=00:11:22:33:44:55,192.168.10.50" in dnsmasq_text
    run(database, "dhcp-export", "--format", "dnsmasq", "--output", dnsmasq_export, expected=2)
    isc_export = root / "exports" / "tomos-phones-isc.conf"
    run(database, "dhcp-export", "--format", "isc-dhcpd", "--output", isc_export)
    isc_text = isc_export.read_text(encoding="utf-8")
    assert "host tomos-phone-001122334455" in isc_text
    assert "hardware ethernet 00:11:22:33:44:55;" in isc_text
    assert "fixed-address 192.168.10.50;" in isc_text
    run(database, "device", "update", "--mac", "001122334455",
        "--dhcp-address", "not-an-ip", expected=2)
    run(database, "device", "add", "--mac", "001122334466", "--model", "7960",
        "--template-family", "7940_7960", "--extension", "1001",
        "--description", "Duplicate IP", "--dhcp-address", "192.168.10.50", expected=2)
    backup_target = root / "exports" / "overwrite.conf"
    backup_target.write_text("existing config\n", encoding="utf-8")
    run(database, "dhcp-export", "--format", "dnsmasq", "--output", backup_target,
        "--force")
    assert pathlib.Path(str(backup_target) + ".tomos-backup").read_text(encoding="utf-8") == "existing config\n"

    # Duplicate MACs and unsupported vendor/template families are rejected.
    run(database, *add_args, expected=2)
    run(database, "device", "add", "--mac", "001122334466", "--vendor", "other",
        "--model", "7960", "--template-family", "7940_7960",
        "--extension", "1001", "--description", "Bad vendor", expected=2)
    run(database, "device", "add", "--mac", "001122334477", "--model", "7960",
        "--template-family", "unknown", "--extension", "1002",
        "--description", "Bad template", expected=2)
    run(database, "device", "add", "--mac", "001122334488", "--model", "7960",
        "--template-family", "7940_7960", "--extension", "1003",
        "--description", "Bad\n[general]", expected=2)

    # Manager delegates output generation to the existing, tested renderer.
    rendered = run(database, "render", "--output-dir", output)
    assert "Managed inventory: 1 phone(s)." in rendered.stdout
    hardware = (output / "sccp_hardware.conf").read_text(encoding="utf-8")
    assert "[SEP001122334455]" in hardware
    assert "description = Main reception" in hardware
    assert "devicetype = 7960" in hardware
    run(database, "render", "--output-dir", output, expected=2)

    run(database, "device", "remove", "--mac", "001122334455", expected=2)
    run(database, "device", "remove", "--mac", "001122334455", "--confirm")
    assert "No phones registered yet" in run(database, "device", "list").stdout
    assert "phone not found" in run(database, "device", "remove", "--mac", "001122334455",
                                    "--confirm", expected=2).stderr

print("TomOS SCCP manager tests passed.")
