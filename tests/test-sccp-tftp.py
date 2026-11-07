#!/usr/bin/env python3
"""Tests for safe Cisco XMLDefault.cnf.xml generation."""
import pathlib
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/tomos-sccp-tftp.py"


def run(*args, expected=0):
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                            text=True, capture_output=True)
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    output = root / "XMLDefault.cnf.xml"
    run("--pbx-address", "192.168.10.5", "--port", "2000", "--output", output)
    tree = ET.parse(output)
    members = tree.findall("./callManagerGroup/members/member")
    assert len(members) == 1
    assert members[0].findtext("./callManager/ports/ethernetPhonePort") == "2000"
    assert members[0].findtext("./callManager/processNodeName") == "192.168.10.5"
    original = output.read_text(encoding="utf-8")
    run("--pbx-address", "192.168.10.6", "--output", output, expected=2)
    assert output.read_text(encoding="utf-8") == original
    run("--pbx-address", "192.168.10.6", "--backup-pbx-address", "192.168.10.7",
        "--output", output, "--force")
    assert output.with_name(output.name + ".tomos-backup").read_text(encoding="utf-8") == original
    members = ET.parse(output).findall("./callManagerGroup/members/member")
    assert len(members) == 2
    run("--pbx-address", "not-an-ip", "--output", root / "bad.xml", expected=2)
    run("--pbx-address", "192.168.1.1", "--port", "0", "--output", root / "bad.xml", expected=2)
    tftp = root / "tftp"
    tftp.mkdir()
    run("--pbx-address", "192.168.1.1", "--output", tftp, "--deploy")
    assert (tftp / "XMLDefault.cnf.xml").is_file()

print("Cisco TFTP XML generation tests passed.")
