#!/usr/bin/env python3
"""Tests for the native TomOS SCCP inventory manager."""
import json
import pathlib
import subprocess
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET

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
    run(database, "device", "buttons", "--mac", "001122334455", "--extensions", "1000,1001")
    button_data = json.loads(run(database, "device", "show", "--mac", "001122334455", "--json").stdout)
    assert button_data["button_extensions"] == "1000,1001"
    run(database, "device", "button-add", "--mac", "001122334455", "--type", "speeddial",
        "--label", "Reception", "--option1", "2000", "--option2", "2000@hints")
    run(database, "device", "button-add", "--mac", "001122334455", "--type", "feature",
        "--label", "Do Not Disturb", "--option1", "DND", "--option2", "busy")
    run(database, "device", "button-add", "--mac", "001122334455", "--type", "speeddial",
        "--label", "Invalid", "--option1", "2000;reboot", expected=2)
    button_data = json.loads(run(database, "device", "show", "--mac", "001122334455", "--json").stdout)
    assert [item["button_type"] for item in button_data["buttons"]] == ["line", "line", "speeddial", "feature"]
    run(database, "device", "buttons", "--mac", "001122334455", "--extensions", "1000,1001")
    button_data = json.loads(run(database, "device", "show", "--mac", "001122334455", "--json").stdout)
    assert [item["button_type"] for item in button_data["buttons"]] == ["line", "line", "speeddial", "feature"]
    run(database, "line", "update", "--extension", "1001", "--label", "Support",
        "--description", "Support desk", "--context", "from-internal-xfer")
    preview = json.loads(run(database, "preview").stdout)
    assert preview["device_count"] == 1 and preview["button_count"] == 4
    assert ("button = line, 1000\nbutton = line, 1001\n"
            'button = speeddial, "Reception", 2000, 2000@hints\n'
            'button = feature, "Do Not Disturb", dnd, busy') in preview["files"]["sccp_hardware.conf"]
    assert "[1001]" in preview["files"]["sccp_extensions.conf"]

    shared_inventory = json.loads(run(database, "device", "list", "--json").stdout)
    assert len(shared_inventory) == 1
    assert shared_inventory[0]["mac"] == "001122334455"
    assert shared_inventory[0]["dhcp_address"] == "192.168.10.50"
    assert json.loads(run(database, "device", "show", "--mac", "001122334455", "--json").stdout)["extension"] == "1000"
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
        "--description", "Bad\\n[general]", expected=2)

    # Manager delegates output generation to the existing, tested renderer.
    rendered = run(database, "render", "--output-dir", output)
    assert "Managed inventory: 1 phone(s)." in rendered.stdout
    hardware = (output / "sccp_hardware.conf").read_text(encoding="utf-8")
    assert "[SEP001122334455]" in hardware
    assert "description = Main reception" in hardware
    assert "devicetype = 7960" in hardware
    assert ("button = line, 1000\nbutton = line, 1001\n"
            'button = speeddial, "Reception", 2000, 2000@hints\n'
            'button = feature, "Do Not Disturb", dnd, busy') in hardware
    run(database, "device", "button-remove", "--mac", "001122334455", "--position", "4")
    after_remove = json.loads(run(database, "device", "show", "--mac", "001122334455", "--json").stdout)
    assert [(item["position"], item["button_type"]) for item in after_remove["buttons"]] == [
        (1, "line"), (2, "line"), (3, "speeddial")]

    assert "[1001]" in (output / "sccp_extensions.conf").read_text(encoding="utf-8")
    run(database, "render", "--output-dir", output, expected=2)


    # Inventory-driven SEP export uses the selected family and stays in staging.
    sep_templates = root / "sep-templates"
    sep_templates.mkdir()
    (sep_templates / "SEP0000000000.cnf.xml_7940_7960_template").write_text(
        '<?xml version="1.0"?><device><devicePool><callManagerGroup><members>'
        '<member><callManager><ports><ethernetPhonePort>2000</ethernetPhonePort>'
        '</ports><processNodeName>x.x.x.x</processNodeName></callManager></member>'
        '</members></callManagerGroup></devicePool></device>', encoding="utf-8")
    sep_output = root / "tftp-review"
    sep_result = run(database, "sep-export", "--pbx-address", "192.168.10.5",
                     "--template-dir", sep_templates, "--output-dir", sep_output)
    assert "XML-validated 1 Cisco SEP file(s)" in sep_result.stdout
    sep_file = sep_output / "SEP001122334455.cnf.xml"
    assert ET.parse(sep_file).findtext(".//processNodeName") == "192.168.10.5"
    original_sep = sep_file.read_text(encoding="utf-8")
    run(database, "sep-export", "--pbx-address", "192.168.10.5",
        "--template-dir", sep_templates, "--output-dir", sep_output, expected=2)
    assert sep_file.read_text(encoding="utf-8") == original_sep
    run(database, "sep-export", "--pbx-address", "192.168.10.5",
        "--template-dir", sep_templates, "--output-dir", sep_output, "--force")
    assert pathlib.Path(str(sep_file) + ".tomos-backup").read_text(encoding="utf-8") == original_sep
    failed_output = root / "sep-failed"
    run(database, "sep-export", "--pbx-address", "192.168.10.5",
        "--template-dir", root / "missing-templates", "--output-dir", failed_output,
        expected=2)
    assert not failed_output.exists()


    # TFTP deployment requires the exact reviewed manifest digest.
    import hashlib
    manifest_file = sep_output / "tomos-sccp-sep-manifest.json"
    manifest_hash = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    tftp_root = root / "live-tftp"
    tftp_root.mkdir()
    run(database, "sep-deploy", "--staging-dir", sep_output, "--tftp-root", tftp_root,
        "--approve-sha256", "0" * 64, expected=2)
    run(database, "sep-deploy", "--staging-dir", sep_output, "--tftp-root", tftp_root,
        "--approve-sha256", manifest_hash)
    deployed = tftp_root / "SEP001122334455.cnf.xml"
    assert deployed.read_bytes() == sep_file.read_bytes()
    deployed.write_text("existing live file", encoding="utf-8")
    run(database, "sep-deploy", "--staging-dir", sep_output, "--tftp-root", tftp_root,
        "--approve-sha256", manifest_hash, expected=2)
    run(database, "sep-deploy", "--staging-dir", sep_output, "--tftp-root", tftp_root,
        "--approve-sha256", manifest_hash, "--force")
    assert pathlib.Path(str(deployed) + ".tomos-backup").read_text(encoding="utf-8") == "existing live file"
    sep_file.write_text(sep_file.read_text(encoding="utf-8") + "<!-- changed -->\\n", encoding="utf-8")
    run(database, "sep-deploy", "--staging-dir", sep_output, "--tftp-root", tftp_root,
        "--approve-sha256", manifest_hash, expected=2)

    fake_asterisk = root / "fake-asterisk"
    fake_asterisk.write_text("#!/bin/sh\nprintf '%s\\n' 'SEP001122334455 001122334455 Registered'\n", encoding="utf-8")
    fake_asterisk.chmod(0o755)
    live_status = json.loads(run(database, "status", "--asterisk-bin", fake_asterisk).stdout)
    assert live_status["devices"][0]["state"] == "registered"

    run(database, "device", "remove", "--mac", "001122334455", expected=2)
    run(database, "device", "remove", "--mac", "001122334455", "--confirm")
    assert "No phones registered yet" in run(database, "device", "list").stdout
    assert "phone not found" in run(database, "device", "remove", "--mac", "001122334455",
                                    "--confirm", expected=2).stderr

    # Existing installations with the original line-only button table migrate in place.
    legacy_db = root / "legacy" / "phones.db"
    run(legacy_db, "init")
    run(legacy_db, "device", "add", "--mac", "AABBCCDDEEFF", "--model", "7960",
        "--template-family", "7940_7960", "--extension", "2000", "--description", "Legacy phone")
    legacy_connection = sqlite3.connect(legacy_db)
    legacy_connection.execute("PRAGMA foreign_keys=OFF")
    legacy_connection.execute("DROP TABLE device_buttons")
    legacy_connection.execute("""
        CREATE TABLE device_buttons (
            mac TEXT NOT NULL REFERENCES devices(mac) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 32),
            button_type TEXT NOT NULL CHECK(button_type IN ('line')),
            line_extension TEXT NOT NULL REFERENCES lines(extension),
            PRIMARY KEY(mac, position)
        )
    """)
    legacy_connection.execute(
        "INSERT INTO device_buttons VALUES ('AABBCCDDEEFF',1,'line','2000')")
    legacy_connection.commit()
    legacy_connection.close()
    run(legacy_db, "init")
    migrated = json.loads(run(legacy_db, "device", "show", "--mac", "AABBCCDDEEFF", "--json").stdout)
    assert migrated["buttons"][0]["button_type"] == "line"
    run(legacy_db, "device", "button-add", "--mac", "AABBCCDDEEFF", "--type", "speeddial",
        "--label", "Operator", "--option1", "0")
    assert len(json.loads(run(legacy_db, "device", "show", "--mac", "AABBCCDDEEFF", "--json").stdout)["buttons"]) == 2

print("TomOS SCCP manager tests passed.")
