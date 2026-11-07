#!/usr/bin/env python3
"""Integration tests for the TomOS SCCP provisioning renderer."""
import json
import pathlib
import subprocess
import sys
import tempfile

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts/tomos-sccp-provision.py"


def run(*args, expected=0):
    result = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                            text=True, capture_output=True)
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    source = root / "phones.json"
    output = root / "generated"
    valid = {
        "server": {"context": "from-internal-xfer"},
        "devices": [
            {"mac": "001122334455", "model": "7960", "description": "Front desk",
             "extension": "1000", "label": "Front desk", "cid_name": "Front Desk"},
            {"mac": "001122334466", "model": "7940", "description": "Reception spare",
             "extension": "1000", "label": "Front desk", "cid_name": "Front Desk"}
        ]
    }
    source.write_text(json.dumps(valid), encoding="utf-8")
    assert "2 device(s), 1 unique line(s)" in run("validate", "--input", source).stdout
    result = run("render", "--input", source, "--output-dir", output)
    assert "staging files only" in result.stdout
    hardware = (output / "sccp_hardware.conf").read_text(encoding="utf-8")
    extensions = (output / "sccp_extensions.conf").read_text(encoding="utf-8")
    assert "[SEP001122334455]" in hardware and "[SEP001122334466]" in hardware
    assert hardware.count("button = line, 1000") == 2
    assert extensions.count("[1000]") == 1
    assert "context = from-internal-xfer" in extensions

    # Never overwrite existing output without an explicit force option.
    run("render", "--input", source, "--output-dir", output, expected=2)
    assert (output / "sccp_hardware.conf").read_text(encoding="utf-8") == hardware
    run("render", "--input", source, "--output-dir", output, "--force")
    assert (output / "sccp_hardware.conf.tomos-backup").read_text(encoding="utf-8") == hardware

    # Preflight every destination before writing either output.
    partial = root / "partial"
    partial.mkdir()
    (partial / "sccp_extensions.conf").write_text("keep existing", encoding="utf-8")
    run("render", "--input", source, "--output-dir", partial, expected=2)
    assert not (partial / "sccp_hardware.conf").exists()
    assert (partial / "sccp_extensions.conf").read_text(encoding="utf-8") == "keep existing"

    # Reject malformed MACs, config injection and conflicting shared-line settings.
    invalid = json.loads(json.dumps(valid))
    invalid["devices"][0]["mac"] = "00:11:22:33:44:55"
    source.write_text(json.dumps(invalid), encoding="utf-8")
    run("validate", "--input", source, expected=2)
    invalid = json.loads(json.dumps(valid))
    invalid["devices"][0]["description"] = "Phone\n[general]"
    source.write_text(json.dumps(invalid), encoding="utf-8")
    run("validate", "--input", source, expected=2)
    invalid = json.loads(json.dumps(valid))
    invalid["devices"][1]["label"] = "Different line label"
    source.write_text(json.dumps(invalid), encoding="utf-8")
    run("validate", "--input", source, expected=2)

print("SCCP provisioning tests passed.")
