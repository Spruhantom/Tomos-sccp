#!/usr/bin/env python3
import pathlib
import subprocess
import sys
import tempfile

script = pathlib.Path(__file__).resolve().parents[1] / "scripts/manage-modules-conf.py"
with tempfile.TemporaryDirectory() as directory:
    target = pathlib.Path(directory) / "modules.conf"
    original = "[modules]\nautoload = yes\n\n[options]\nverbose = 3\n"
    target.write_text(original, encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(target)], check=True)
    first = target.read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(script), str(target)], check=True)
    second = target.read_text(encoding="utf-8")
    assert first == second, "managed block is not idempotent"
    assert second.count("; BEGIN TOMOS-SCCP MANAGED BLOCK") == 1
    assert "[options]\nverbose = 3" in second
    assert "noload => chan_skinny.so" in second
    assert "load => chan_sccp.so" in second
print("modules.conf management tests passed.")
