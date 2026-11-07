#!/usr/bin/env python3
"""Render an upstream Cisco SEP<MAC>.cnf.xml model template safely."""
import argparse
import ipaddress
import os
import pathlib
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

MODELS = ("69xx", "791x", "7925", "7937", "7940_7960", "796x", "797x", "797x_extended")
MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")


class SepConfigError(ValueError):
    pass


def render(template_path, mac, pbx_address, port=2000, ntp_server=None,
           ssh_user=None, ssh_password_file=None):
    if not MAC_RE.fullmatch(mac):
        raise SepConfigError("MAC address must contain exactly 12 hexadecimal characters")
    try:
        pbx_address = str(ipaddress.IPv4Address(pbx_address))
        if ntp_server:
            ntp_server = str(ipaddress.IPv4Address(ntp_server))
    except ValueError as exc:
        raise SepConfigError(f"PBX and NTP addresses must be valid IPv4 literals: {exc}") from exc
    if not 1 <= port <= 65535:
        raise SepConfigError("SCCP port must be between 1 and 65535")
    if bool(ssh_user) != bool(ssh_password_file):
        raise SepConfigError("--ssh-user and --ssh-password-file must be supplied together")

    try:
        tree = ET.parse(template_path)
    except (ET.ParseError, OSError) as exc:
        raise SepConfigError(f"could not read a valid upstream XML template: {exc}") from exc
    root = tree.getroot()
    if root.tag != "device":
        raise SepConfigError("upstream model template must have a <device> root element")

    ssh_user_element = root.find("sshUserId")
    ssh_password_element = root.find("sshPassword")
    if ssh_user_element is not None and ssh_password_element is not None:
        if ssh_user:
            if any(char in ssh_user for char in "\r\n<>\x00"):
                raise SepConfigError("SSH username contains characters unsafe for XML text")
            password_path = pathlib.Path(ssh_password_file)
            if password_path.is_symlink() or not password_path.is_file():
                raise SepConfigError("SSH password file must be an existing regular non-symlink file")
            if password_path.stat().st_mode & 0o077:
                raise SepConfigError("SSH password file permissions must be 0600 or stricter")
            password = password_path.read_text(encoding="utf-8").rstrip("\r\n")
            if not password or any(char in password for char in "\r\n<>\x00"):
                raise SepConfigError("SSH password file must contain one non-empty XML-safe line")
            ssh_user_element.text = ssh_user
            ssh_password_element.text = password
        else:
            # Never ship the upstream cisco/cisco example credentials.
            root.remove(ssh_user_element)
            root.remove(ssh_password_element)

    # Upstream templates use x.x.x.x for the PBX address. The 797x template
    # also contains a sample public NTP address; never ship that example.
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag == "ntp" and child.findtext("name", "").strip() == "213.109.127.195":
                if ntp_server:
                    child.find("name").text = ntp_server
                else:
                    parent.remove(child)
        if parent.text:
            parent.text = parent.text.replace("x.x.x.x", pbx_address)
        for value in parent.attrib.values():
            if "x.x.x.x" in value:
                raise SepConfigError("unsupported address placeholder in XML attribute")

    for element in root.iter("ethernetPhonePort"):
        element.text = str(port)
    for element in root.iter("port1"):
        if element.text == "2000":
            element.text = str(port)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def write_safe(destination, content, force=False):
    destination = pathlib.Path(destination)
    if destination.exists() and not force:
        raise SepConfigError(f"refusing to overwrite {destination}; use --force to preserve a backup")
    backup = destination.with_name(destination.name + ".tomos-backup")
    if destination.exists() and backup.exists():
        raise SepConfigError(f"backup already exists: {backup}; move it before using --force")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    moved = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, 0o644)
        if destination.exists():
            os.replace(destination, backup)
            moved = True
        try:
            os.replace(temporary, destination)
        except OSError:
            if moved and backup.exists() and not destination.exists():
                os.replace(backup, destination)
                moved = False
            raise
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, choices=MODELS)
    parser.add_argument("--mac", required=True, help="12-hex-digit Cisco phone MAC address")
    parser.add_argument("--pbx-address", required=True, help="phone-reachable PBX IPv4 address")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--ntp-server", help="optional NTP server IPv4 address")
    parser.add_argument("--ssh-user", help="optional phone SSH username; pair with --ssh-password-file")
    parser.add_argument("--ssh-password-file", help="0600 file containing the phone SSH password")
    parser.add_argument("--template-dir", default="/usr/share/tomos-sccp/tftp-templates")
    parser.add_argument("--output", required=True, help="output filename or existing TFTP root with --deploy")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        template = pathlib.Path(args.template_dir) / f"SEP0000000000.cnf.xml_{args.model}_template"
        content = render(template, args.mac, args.pbx_address, args.port, args.ntp_server,
                         args.ssh_user, args.ssh_password_file)
        output = pathlib.Path(args.output)
        if args.deploy:
            if not output.is_dir():
                raise SepConfigError("--deploy requires --output to be an existing TFTP root directory")
            output = output / f"SEP{args.mac.upper()}.cnf.xml"
        elif output.exists() and output.is_dir():
            raise SepConfigError("without --deploy, --output must be a file path")
        write_safe(output, content, args.force)
        ET.parse(output)
        print(f"Generated {output}")
        print(f"Template family: {args.model}; verify firmware and handset compatibility before deployment.")
        return 0
    except (SepConfigError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
