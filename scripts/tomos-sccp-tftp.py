#!/usr/bin/env python3
"""Generate or safely deploy a minimal Cisco XMLDefault.cnf.xml for chan-sccp.

The PBX address is the phone-reachable address, not necessarily the server's
bind address. Firmware load strings are intentionally omitted: firmware must
be selected and tested for each phone model separately.
"""
import argparse
import ipaddress
import os
import pathlib
import sys
import tempfile
import xml.etree.ElementTree as ET


class TftpConfigError(ValueError):
    pass


def build_xml(host, port, backup_host=None):
    try:
        host = str(ipaddress.IPv4Address(host))
        if backup_host:
            backup_host = str(ipaddress.IPv4Address(backup_host))
    except ValueError as exc:
        raise TftpConfigError(f"PBX addresses must be valid IPv4 literals: {exc}") from exc
    if not 1 <= port <= 65535:
        raise TftpConfigError("SCCP port must be between 1 and 65535")
    if backup_host == host:
        raise TftpConfigError("primary and backup PBX addresses must differ")

    root = ET.Element("Default")
    group = ET.SubElement(root, "callManagerGroup")
    members = ET.SubElement(group, "members")
    for priority, address in enumerate([host] + ([backup_host] if backup_host else [])):
        member = ET.SubElement(members, "member", {"priority": str(priority)})
        manager = ET.SubElement(member, "callManager")
        ports = ET.SubElement(manager, "ports")
        ET.SubElement(ports, "ethernetPhonePort").text = str(port)
        ET.SubElement(manager, "processNodeName").text = address
    ET.indent(root, space="    ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_safe(destination, content, force=False):
    destination = pathlib.Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(destination.name + ".tomos-backup")
    if destination.exists() and not force:
        raise TftpConfigError(f"refusing to overwrite {destination}; use --force after backing it up")
    if destination.exists() and backup.exists():
        raise TftpConfigError(f"backup already exists: {backup}; move it before using --force")
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    moved_original = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        if destination.exists():
            os.replace(destination, backup)
            moved_original = True
        try:
            os.replace(temporary, destination)
        except OSError:
            if moved_original and backup.exists() and not destination.exists():
                os.replace(backup, destination)
                moved_original = False
            raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbx-address", required=True, help="phone-reachable PBX IPv4 address")
    parser.add_argument("--port", type=int, default=2000, help="SCCP TCP port (default: 2000)")
    parser.add_argument("--backup-pbx-address", help="optional secondary phone-reachable PBX address")
    parser.add_argument("--output", required=True, help="output file or TFTP-root/XMLDefault.cnf.xml")
    parser.add_argument("--deploy", action="store_true", help="write directly into the specified TFTP root")
    parser.add_argument("--force", action="store_true", help="preserve an existing file as .tomos-backup before replacing")
    args = parser.parse_args()
    try:
        content = build_xml(args.pbx_address, args.port, args.backup_pbx_address)
        output = pathlib.Path(args.output)
        if args.deploy:
            if not output.is_dir():
                raise TftpConfigError("--deploy requires --output to be an existing TFTP root directory")
            output = output / "XMLDefault.cnf.xml"
        elif output.exists() and output.is_dir():
            raise TftpConfigError("without --deploy, --output must be a file path")
        write_safe(output, content, args.force)
        # Parse the written result as a final well-formedness check.
        ET.parse(output)
        print(f"Generated {output}")
        print("Firmware load settings are omitted; select and test firmware per phone model.")
        return 0
    except (TftpConfigError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
