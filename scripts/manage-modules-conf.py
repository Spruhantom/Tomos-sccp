#!/usr/bin/env python3
"""Atomically manage only the TomOS-owned modules.conf block."""
import os
import pathlib
import re
import sys
import tempfile

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/etc/asterisk/modules.conf")
begin = "; BEGIN TOMOS-SCCP MANAGED BLOCK"
end = "; END TOMOS-SCCP MANAGED BLOCK"
text = path.read_text(encoding="utf-8") if path.exists() else ""
mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
pattern = re.compile(rf"(?ms)^{re.escape(begin)}\n.*?^{re.escape(end)}\n?")
text = pattern.sub("", text)
block = f"{begin}\nnoload => chan_skinny.so\nload => chan_sccp.so\n{end}"
lines = text.splitlines()
section = next((i for i, line in enumerate(lines)
                if re.match(r"^\s*\[modules\]\s*(?:;.*)?$", line, re.I)), None)
if section is None:
    if text and not text.endswith("\n"):
        text += "\n"
    if text.strip():
        text += "\n"
    text += "[modules]\n" + block + "\n"
else:
    section_end = next((i for i in range(section + 1, len(lines))
                        if re.match(r"^\s*\[[^]]+\]", lines[i])), len(lines))
    lines.insert(section_end, block)
    text = "\n".join(lines).rstrip() + "\n"
path.parent.mkdir(parents=True, exist_ok=True)
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.chmod(temporary, mode)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
