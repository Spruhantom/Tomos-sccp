#!/usr/bin/env python3
"""CI fixture checks for initial Cisco model/template compatibility targets.

These tests exercise TomOS selection and XML transformation only. They do not
emulate Cisco firmware, run chan-sccp or establish physical compatibility.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANAGER = ROOT / "scripts/tomos-sccp-manager.py"
SEP = ROOT / "scripts/tomos-sccp-sep.py"
TARGETS = {"7940": "7940_7960", "7960": "7940_7960", "7970": "797x"}


def run(script, *args, expected=0):
    result = subprocess.run([sys.executable, str(script), *map(str, args)],
                            text=True, capture_output=True)
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory() as temporary:
    root = pathlib.Path(temporary)
    database = root / "inventory.db"
    run(MANAGER, "--database", database, "init")

    for index, (model, family) in enumerate(TARGETS.items(), start=1):
        mac = f"0011223344{index:02X}"
        run(MANAGER, "--database", database, "device", "add",
            "--mac", mac, "--vendor", "cisco", "--model", model,
            "--template-family", family, "--extension", str(1100 + index),
            "--description", f"Test Cisco {model}")
        wrong_family = "797x" if family == "7940_7960" else "7940_7960"
        run(MANAGER, "--database", database, "device", "add",
            "--mac", f"0011223355{index:02X}", "--vendor", "cisco",
            "--model", model, "--template-family", wrong_family,
            "--extension", str(1200 + index), "--description", "Wrong template",
            expected=2)

    # Updates must enforce the same model/template invariant as creation.
    run(MANAGER, "--database", database, "device", "update",
        "--mac", "001122334401", "--template-family", "797x", expected=2)

    inventory = json.loads(run(MANAGER, "--database", database,
                               "device", "list", "--json").stdout)
    assert {item["model_number"]: item["template_family"] for item in inventory} == TARGETS

    templates = root / "templates"
    templates.mkdir()
    for family in set(TARGETS.values()):
        template = templates / f"SEP0000000000.cnf.xml_{family}_template"
        template.write_text(
            '<?xml version="1.0"?><device><sshUserId>cisco</sshUserId>'
            '<sshPassword>cisco</sshPassword><devicePool><callManagerGroup><members>'
            '<member><callManager><ports><ethernetPhonePort>2000</ethernetPhonePort>'
            '</ports><processNodeName>x.x.x.x</processNodeName></callManager></member>'
            '</members></callManagerGroup></devicePool></device>',
            encoding="utf-8")

    for index, (model, family) in enumerate(TARGETS.items(), start=1):
        mac = f"0011223344{index:02X}"
        output = root / f"SEP{mac}.cnf.xml"
        run(SEP, "--model", family, "--mac", mac, "--pbx-address",
            "192.0.2.10", "--template-dir", templates, "--output", output)
        tree = ET.parse(output)
        assert tree.getroot().tag == "device"
        assert tree.findtext(".//processNodeName") == "192.0.2.10"
        assert tree.findtext(".//ethernetPhonePort") == "2000"
        assert tree.find("./sshUserId") is None
        assert tree.find("./sshPassword") is None
        xml = output.read_text(encoding="utf-8")
        assert "x.x.x.x" not in xml
        assert "cisco" not in xml

print("Cisco 7940/7960/7970 model/template fixture checks passed.")
