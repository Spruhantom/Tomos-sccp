#!/usr/bin/env python3
"""Tests for Cisco per-device SEP XML rendering."""
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/tomos-sccp-sep.py"

with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    templates = root / "templates"
    templates.mkdir()
    template = templates / "SEP0000000000.cnf.xml_69xx_template"
    template.write_text("""<?xml version="1.0"?><device><sshUserId>cisco</sshUserId><sshPassword>cisco</sshPassword><devicePool><callManagerGroup><members><member priority="0"><callManager><ports><ethernetPhonePort>2000</ethernetPhonePort></ports><processNodeName>x.x.x.x</processNodeName></callManager></member></members></callManagerGroup><dateTimeSetting><ntps><ntp><name>213.109.127.195</name></ntp></ntps></dateTimeSetting><srstInfo><ipAddr1>x.x.x.x</ipAddr1><port1>2000</port1></srstInfo></devicePool></device>""", encoding="utf-8")
    output = root / "SEP001122AABBCC.cnf.xml"

    def run(*args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                                text=True, capture_output=True)
        assert result.returncode == expected, (result.stdout, result.stderr)
        return result

    base = ["--model", "69xx", "--mac", "001122aabbcc", "--pbx-address", "192.168.1.10",
            "--template-dir", templates, "--output", output]
    run(*base)
    tree = ET.parse(output)
    assert tree.findtext(".//processNodeName") == "192.168.1.10"\n    assert tree.findtext("./sshUserId") == "tom-phone"\n    assert tree.findtext("./sshPassword") == "change-me"
    assert tree.findtext(".//ethernetPhonePort") == "2000"
    assert tree.findtext(".//ipAddr1") == "192.168.1.10"
    assert tree.find(".//ntp") is None
    original = output.read_text(encoding="utf-8")
    run(*base, expected=2)
    assert output.read_text(encoding="utf-8") == original
    run(*base, "--force", "--ntp-server", "192.168.1.20")
    assert output.with_name(output.name + ".tomos-backup").read_text(encoding="utf-8") == original
    assert ET.parse(output).findtext(".//ntp/name") == "192.168.1.20"
    run("--model", "69xx", "--mac", "bad", "--pbx-address", "192.168.1.10",
        "--template-dir", templates, "--output", root / "bad.xml", expected=2)
    run("--model", "69xx", "--mac", "001122aabbcc", "--pbx-address", "not-an-ip",
        "--template-dir", templates, "--output", root / "bad.xml", expected=2)
    tftp = root / "tftp"
    tftp.mkdir()
    run("--model", "69xx", "--mac", "001122aabbcc", "--pbx-address", "192.168.1.10",
        "--template-dir", templates, "--output", tftp, "--deploy")
    assert (tftp / "SEP001122AABBCC.cnf.xml").is_file()

print("Cisco per-device SEP XML tests passed.")
