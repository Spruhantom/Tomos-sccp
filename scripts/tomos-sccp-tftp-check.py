#!/usr/bin/env python3
"""Read back reviewed Cisco SEP XML files from a live TFTP server.

This verifies TFTP retrieval and byte-for-byte agreement with the approved
local manifest. It does not prove handset firmware compatibility or SCCP
registration.
"""
import argparse
import hashlib
import ipaddress
import json
import pathlib
import re
import socket
import struct
import sys
import xml.etree.ElementTree as ET


MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
BLOCK_SIZE = 512


class CheckError(ValueError):
    """Raised when a TFTP read-back check fails."""


def read_tftp_file(server, filename, port=69, timeout=2.0, retries=3):
    """Read one file using RFC 1350 octet-mode RRQ."""
    request = struct.pack("!H", 1) + filename.encode("ascii") + b"\0octet\0"
    result = bytearray()
    expected_block = 1
    transfer_id = None
    last_packet = request

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        for attempt in range(retries + 1):
            sock.sendto(last_packet, (server, port) if transfer_id is None else transfer_id)
            try:
                while True:
                    packet, peer = sock.recvfrom(4 + BLOCK_SIZE + 4)
                    if peer[0] != server:
                        continue
                    if transfer_id is None:
                        transfer_id = peer
                    elif peer != transfer_id:
                        continue
                    if len(packet) < 4:
                        raise CheckError(f"{filename}: malformed TFTP packet")
                    opcode, block = struct.unpack("!HH", packet[:4])
                    if opcode == 5:
                        code = struct.unpack("!H", packet[2:4])[0]
                        message = packet[4:].split(b"\0", 1)[0].decode("ascii", "replace")
                        raise CheckError(f"{filename}: TFTP error {code}: {message}")
                    if opcode != 3:
                        raise CheckError(f"{filename}: expected TFTP DATA, received opcode {opcode}")
                    if block == expected_block:
                        payload = packet[4:]
                        if len(payload) > BLOCK_SIZE:
                            raise CheckError(f"{filename}: oversized TFTP data block")
                        result.extend(payload)
                        last_packet = struct.pack("!HH", 4, block)
                        sock.sendto(last_packet, transfer_id)
                        expected_block = (expected_block + 1) & 0xffff
                        if len(payload) < BLOCK_SIZE:
                            return bytes(result)
                    elif block == ((expected_block - 1) & 0xffff):
                        sock.sendto(last_packet, transfer_id)
                    else:
                        raise CheckError(f"{filename}: unexpected TFTP block {block}")
            except socket.timeout:
                if attempt >= retries:
                    raise CheckError(f"{filename}: TFTP read timed out after {retries + 1} attempts")
                continue
    raise CheckError(f"{filename}: TFTP read failed")


def load_manifest(staging_dir):
    manifest_path = staging_dir / "tomos-sccp-sep-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise CheckError("manifest is missing or is not a regular file")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckError(f"invalid manifest: {exc}") from exc
    if manifest.get("schema_version") != 1:
        raise CheckError("unsupported SEP manifest schema")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise CheckError("SEP manifest has no files")
    seen = set()
    validated = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise CheckError("manifest contains a malformed file entry")
        mac = entry.get("mac", "")
        filename = entry.get("filename", "")
        digest = entry.get("sha256", "")
        if not isinstance(mac, str) or not MAC_RE.fullmatch(mac):
            raise CheckError("manifest contains an invalid MAC address")
        if filename != f"SEP{mac}.cnf.xml" or filename in seen:
            raise CheckError("manifest contains an invalid or duplicate filename")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise CheckError(f"{filename}: invalid SHA-256 value in manifest")
        seen.add(filename)
        source = staging_dir / filename
        if source.is_symlink() or not source.is_file():
            raise CheckError(f"{filename}: staged file is missing or not a regular file")
        local_data = source.read_bytes()
        if hashlib.sha256(local_data).hexdigest() != digest:
            raise CheckError(f"{filename}: staged file no longer matches its manifest checksum")
        try:
            ET.fromstring(local_data)
        except ET.ParseError as exc:
            raise CheckError(f"{filename}: staged file is not valid XML: {exc}") from exc
        validated.append((filename, digest))
    return validated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True, help="IPv4 address of the live TFTP server")
    parser.add_argument("--staging-dir", required=True, help="directory containing the approved SEP export and manifest")
    parser.add_argument("--port", type=int, default=69, help="TFTP UDP port (default: 69)")
    parser.add_argument("--timeout", type=float, default=2.0, help="per-packet timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="number of retries after a timeout")
    args = parser.parse_args()
    try:
        server = str(ipaddress.IPv4Address(args.server))
        if not 1 <= args.port <= 65535:
            raise CheckError("--port must be between 1 and 65535")
        if not 0.1 <= args.timeout <= 60:
            raise CheckError("--timeout must be between 0.1 and 60 seconds")
        if not 0 <= args.retries <= 10:
            raise CheckError("--retries must be between 0 and 10")
        staging_dir = pathlib.Path(args.staging_dir).resolve()
        if not staging_dir.is_dir():
            raise CheckError("staging directory does not exist")
        entries = load_manifest(staging_dir)
        for filename, expected_digest in entries:
            remote_data = read_tftp_file(server, filename, args.port, args.timeout, args.retries)
            actual_digest = hashlib.sha256(remote_data).hexdigest()
            if actual_digest != expected_digest:
                raise CheckError(f"{filename}: TFTP-served content does not match the reviewed manifest")
            try:
                ET.fromstring(remote_data)
            except ET.ParseError as exc:
                raise CheckError(f"{filename}: TFTP server returned invalid XML: {exc}") from exc
            print(f"PASS {filename}: retrieved via TFTP; SHA-256 matches reviewed manifest")
        print(f"Verified {len(entries)} Cisco SEP file(s) from TFTP server {server}:{args.port}.")
        print("This confirms TFTP read-back only; handset parsing, SCCP registration and calls remain separate tests.")
        return 0
    except (CheckError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
