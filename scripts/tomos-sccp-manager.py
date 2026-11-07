#!/usr/bin/env python3
"""Native TomOS SCCP provisioning manager.

Inspired by Endpoint Manager's inventory/model/template separation, but
implemented independently for TomOS and the upstream chan-sccp driver.
"""
import argparse
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

DEFAULT_DB = "/var/lib/tomos-sccp/provisioning.db"
VENDORS = {"cisco": "Cisco"}
TEMPLATE_FAMILIES = {
    "69xx": "Cisco 69xx",
    "791x": "Cisco 791x",
    "7925": "Cisco 7925",
    "7937": "Cisco 7937",
    "7940_7960": "Cisco 7940/7960",
    "796x": "Cisco 796x",
    "797x": "Cisco 797x",
    "797x_extended": "Cisco 797x extended",
}
MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")
MODEL_RE = re.compile(r"^[0-9]{3,4}$")
EXT_RE = re.compile(r"^[0-9]{1,20}$")
CONTEXT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


class ManagerError(ValueError):
    """Raised for invalid manager operations."""


def clean_text(value, field, limit=80):
    if not isinstance(value, str) or not value.strip():
        raise ManagerError(f"{field} must be a non-empty string")
    value = value.strip()
    if len(value) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ManagerError(f"{field} contains control characters or exceeds {limit} characters")
    if any(ch in value for ch in ";[]=#"):
        raise ManagerError(f"{field} contains a character unsafe for Asterisk configuration")
    return value


def connect_database(path):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS vendors (
            slug TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            protocol TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS template_families (
            vendor_slug TEXT NOT NULL REFERENCES vendors(slug),
            slug TEXT NOT NULL,
            display_name TEXT NOT NULL,
            upstream_template TEXT NOT NULL,
            PRIMARY KEY (vendor_slug, slug)
        );
        CREATE TABLE IF NOT EXISTS devices (
            mac TEXT PRIMARY KEY,
            vendor_slug TEXT NOT NULL,
            model_number TEXT NOT NULL,
            template_family TEXT NOT NULL,
            description TEXT NOT NULL,
            extension TEXT NOT NULL,
            label TEXT NOT NULL,
            cid_name TEXT NOT NULL,
            cid_num TEXT NOT NULL,
            context TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (vendor_slug, template_family)
                REFERENCES template_families(vendor_slug, slug)
        );
    """)
    connection.execute(
        "INSERT OR IGNORE INTO vendors(slug, display_name, protocol) VALUES (?, ?, ?)",
        ("cisco", "Cisco", "SCCP")
    )
    for family, display in TEMPLATE_FAMILIES.items():
        connection.execute(
            """INSERT OR IGNORE INTO template_families
               (vendor_slug, slug, display_name, upstream_template)
               VALUES (?, ?, ?, ?)""",
            ("cisco", family, display,
             f"SEP0000000000.cnf.xml_{family}_template")
        )
    connection.commit()
    try:
        os.chmod(path, 0o600)
    except OSError:
        connection.close()
        raise
    return connection


def add_device(db, args):
    vendor = args.vendor.lower()
    if vendor not in VENDORS:
        raise ManagerError(f"unsupported vendor: {vendor}")
    mac = args.mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    model = args.model
    if not MODEL_RE.fullmatch(model):
        raise ManagerError("--model must be a 3- or 4-digit SCCP device type")
    family = args.template_family
    if family not in TEMPLATE_FAMILIES:
        raise ManagerError(f"unsupported Cisco template family: {family}")
    extension = args.extension
    if not EXT_RE.fullmatch(extension):
        raise ManagerError("--extension must contain 1–20 digits")
    context = args.context
    if not CONTEXT_RE.fullmatch(context):
        raise ManagerError("--context may contain only letters, digits, dot, underscore and hyphen")
    description = clean_text(args.description, "--description")
    label = clean_text(args.label or extension, "--label")
    cid_name = clean_text(args.cid_name or label, "--cid-name")
    cid_num = clean_text(args.cid_num or extension, "--cid-num", 40)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db:
            db.execute(
                """INSERT INTO devices
                   (mac, vendor_slug, model_number, template_family, description,
                    extension, label, cid_name, cid_num, context, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mac, vendor, model, family, description, extension, label,
                 cid_name, cid_num, context, now, now)
            )
    except sqlite3.IntegrityError as exc:
        raise ManagerError(f"could not add device (duplicate MAC or unknown vendor/template): {exc}") from exc
    print(f"Added {vendor} {model} phone SEP{mac} on extension {extension}.")


def list_devices(db):
    rows = db.execute(
        """SELECT mac, vendor_slug, model_number, template_family, extension, description
           FROM devices ORDER BY mac"""
    ).fetchall()
    if not rows:
        print("No phones registered yet.")
        return
    print(f"{'MAC':14} {'VENDOR':8} {'MODEL':7} {'TEMPLATE':16} {'EXTENSION':12} DESCRIPTION")
    for row in rows:
        print(f"{row['mac']:14} {row['vendor_slug']:8} {row['model_number']:7} "
              f"{row['template_family']:16} {row['extension']:12} {row['description']}")


def show_device(db, mac):
    mac = mac.replace(":", "").replace("-", "").upper()
    row = db.execute("SELECT * FROM devices WHERE mac = ?", (mac,)).fetchone()
    if row is None:
        raise ManagerError(f"phone not found: {mac}")
    for key in ("mac", "vendor_slug", "model_number", "template_family", "description",
                "extension", "label", "cid_name", "cid_num", "context", "created_at", "updated_at"):
        print(f"{key}: {row[key]}")


def remove_device(db, mac):
    mac = mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    with db:
        cursor = db.execute("DELETE FROM devices WHERE mac = ?", (mac,))
    if cursor.rowcount != 1:
        raise ManagerError(f"phone not found: {mac}")
    print(f"Removed phone SEP{mac} from the inventory. Existing generated files were not changed.")


def render_inventory(db, output_dir, force):
    rows = db.execute("SELECT * FROM devices ORDER BY mac").fetchall()
    if not rows:
        raise ManagerError("inventory is empty; add at least one phone before rendering")
    contexts = {row["context"] for row in rows}
    if len(contexts) != 1:
        raise ManagerError("all devices must use the same dialplan context for the current SCCP renderer")
    inventory = {
        "server": {"context": next(iter(contexts))},
        "devices": [
            {
                "mac": row["mac"],
                "model": row["model_number"],
                "description": row["description"],
                "extension": row["extension"],
                "label": row["label"],
                "cid_name": row["cid_name"],
                "cid_num": row["cid_num"],
            }
            for row in rows
        ],
    }
    helper = pathlib.Path(__file__).with_name("tomos-sccp-provision.py")
    if not helper.is_file():
        raise ManagerError(f"existing SCCP renderer is missing: {helper}")
    with tempfile.TemporaryDirectory(prefix="tomos-sccp-manager-") as temporary:
        source = pathlib.Path(temporary) / "inventory.json"
        source.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
        command = [sys.executable, str(helper), "render", "--input", str(source),
                   "--output-dir", str(output_dir)]
        if force:
            command.append("--force")
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.returncode:
        raise ManagerError(result.stderr.strip() or "SCCP renderer failed")
    print(f"Managed inventory: {len(rows)} phone(s).")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.environ.get("TOMOS_SCCP_DB", DEFAULT_DB),
                        help=f"inventory database (default: {DEFAULT_DB})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create the local inventory database")
    vendor = sub.add_parser("vendor", help="show supported phone vendors")
    vendor.add_argument("action", choices=("list",))
    model = sub.add_parser("model", help="show available upstream model templates")
    model.add_argument("action", choices=("list",))
    model.add_argument("--vendor", choices=tuple(VENDORS), default="cisco")

    device = sub.add_parser("device", help="manage provisioned phones")
    device_sub = device.add_subparsers(dest="action", required=True)
    add = device_sub.add_parser("add")
    add.add_argument("--mac", required=True)
    add.add_argument("--vendor", choices=tuple(VENDORS), default="cisco")
    add.add_argument("--model", required=True, help="numeric chan-sccp devicetype")
    add.add_argument("--template-family", required=True, choices=tuple(TEMPLATE_FAMILIES))
    add.add_argument("--extension", required=True)
    add.add_argument("--description", required=True)
    add.add_argument("--label")
    add.add_argument("--cid-name")
    add.add_argument("--cid-num")
    add.add_argument("--context", default="from-internal-xfer")
    listing = device_sub.add_parser("list")
    show = device_sub.add_parser("show")
    show.add_argument("--mac", required=True)
    remove = device_sub.add_parser("remove")
    remove.add_argument("--mac", required=True)
    remove.add_argument("--confirm", action="store_true",
                        help="confirm removing the device from the inventory")

    render = sub.add_parser("render", help="render managed inventory to staging include files")
    render.add_argument("--output-dir", required=True)
    render.add_argument("--force", action="store_true")

    args = parser.parse_args()
    db = None
    try:
        db = connect_database(args.database)
        if args.command == "init":
            print(f"TomOS SCCP provisioning database ready: {args.database}")
        elif args.command == "vendor":
            for slug, name in VENDORS.items():
                print(f"{slug}\t{name}\tSCCP")
        elif args.command == "model":
            for slug, name in TEMPLATE_FAMILIES.items():
                print(f"{slug}\t{name}\t{slug}")
        elif args.command == "device":
            if args.action == "add":
                add_device(db, args)
            elif args.action == "list":
                list_devices(db)
            elif args.action == "show":
                show_device(db, args.mac)
            elif args.action == "remove":
                if not args.confirm:
                    raise ManagerError("removal requires --confirm")
                remove_device(db, args.mac)
        elif args.command == "render":
            render_inventory(db, args.output_dir, args.force)
        return 0
    except (ManagerError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
