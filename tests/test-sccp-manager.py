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
                "--label", "Front desk", "--cid-name", "Front Desk")
    assert "Added cisco 7960" in run(database, *add_args).stdout
    assert "Front desk" in run(database, "device", "list").stdout
    details = run(database, "device", "show", "--mac", "001122334455").stdout
    assert "template_family: 7940_7960" in details
    assert "extension: 1000" in details

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
    assert "devicetype = 7960" in hardware
    run(database, "render", "--output-dir", output, expected=2)

    run(database, "device", "remove", "--mac", "001122334455", expected=2)
    run(database, "device", "remove", "--mac", "001122334455", "--confirm")
    assert "No phones registered yet" in run(database, "device", "list").stdout
    assert "phone not found" in run(database, "device", "remove", "--mac", "001122334455",
                                    "--confirm", expected=2).stderr

print("TomOS SCCP manager tests passed.")
