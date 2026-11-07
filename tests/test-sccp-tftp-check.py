#!/usr/bin/env python3
"""Tests for the TomOS SCCP live TFTP read-back checker."""
import hashlib
import json
import pathlib
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "tomos-sccp-tftp-check.py"


def serve_once(payload, error=None):
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]

    def worker():
        try:
            request, client = server.recvfrom(2048)
            assert struct.unpack("!H", request[:2])[0] == 1
            if error:
                packet = struct.pack("!HH", 5, 1) + error.encode() + b"\0"
                server.sendto(packet, client)
                return
            offset = 0
            block = 1
            while True:
                chunk = payload[offset:offset + 512]
                server.sendto(struct.pack("!HH", 3, block) + chunk, client)
                ack, _ = server.recvfrom(64)
                assert struct.unpack("!HH", ack) == (4, block)
                offset += len(chunk)
                if len(chunk) < 512:
                    break
                block += 1
        finally:
            server.close()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return port, thread


def run(staging, port, expected=0):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--server", "127.0.0.1",
         "--port", str(port), "--staging-dir", str(staging),
         "--timeout", "0.2", "--retries", "0"],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == expected, (result.stdout, result.stderr)
    return result


with tempfile.TemporaryDirectory(prefix="tomos-tftp-check-") as temporary:
    staging = pathlib.Path(temporary)
    xml = ET.tostring(ET.Element("device"), encoding="utf-8", xml_declaration=True)
    filename = "SEP001122334455.cnf.xml"
    (staging / filename).write_bytes(xml)
    manifest = {
        "schema_version": 1,
        "files": [{"mac": "001122334455", "filename": filename,
                   "sha256": hashlib.sha256(xml).hexdigest()}],
    }
    (staging / "tomos-sccp-sep-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    port, thread = serve_once(xml)
    result = run(staging, port)
    assert "matches reviewed manifest" in result.stdout
    thread.join(timeout=1)

    port, thread = serve_once(b"<device/>")
    result = run(staging, port, expected=2)
    assert "does not match the reviewed manifest" in result.stderr
    thread.join(timeout=1)

    port, thread = serve_once(b"", error="file not found")
    result = run(staging, port, expected=2)
    assert "TFTP error 1" in result.stderr
    thread.join(timeout=1)

    (staging / filename).write_bytes(b"<changed/>")
    port, thread = serve_once(b"<changed/>")
    result = run(staging, port, expected=2)
    assert "no longer matches its manifest checksum" in result.stderr
    thread.join(timeout=1)

print("TomOS SCCP TFTP read-back tests passed.")
