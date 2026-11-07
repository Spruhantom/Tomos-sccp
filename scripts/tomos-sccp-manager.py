#!/usr/bin/env python3
"""Native TomOS SCCP provisioning manager.

Inspired by Endpoint Manager's inventory/model/template separation, but
implemented independently for TomOS and the upstream chan-sccp driver.
"""
import argparse
import grp
import pwd
import json
import ipaddress
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
MODEL_TEMPLATE_FAMILIES = {"7940": "7940_7960", "7960": "7940_7960", "7970": "797x"}


class ManagerError(ValueError):
    """Raised for invalid manager operations."""


def validate_model_template(model, family):
    expected = MODEL_TEMPLATE_FAMILIES.get(model)
    if expected and family != expected:
        raise ManagerError(f"Cisco model {model} requires template family {expected}, not {family}")


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
        CREATE TABLE IF NOT EXISTS lines (
            extension TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            description TEXT NOT NULL,
            context TEXT NOT NULL,
            cid_name TEXT NOT NULL,
            cid_num TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS device_buttons (
            mac TEXT NOT NULL REFERENCES devices(mac) ON DELETE CASCADE,
            position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 32),
            button_type TEXT NOT NULL CHECK(button_type IN ('line','speeddial','feature','empty')),
            line_extension TEXT REFERENCES lines(extension),
            button_label TEXT,
            option1 TEXT,
            option2 TEXT,
            PRIMARY KEY(mac, position)
        );
    """)
    button_schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='device_buttons'"
    ).fetchone()["sql"]
    button_columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(device_buttons)")}
    if ("CHECK(button_type IN ('line'))" in button_schema
            or button_columns["line_extension"]["notnull"]):
        connection.execute("ALTER TABLE device_buttons RENAME TO device_buttons_legacy")
        connection.execute("""
            CREATE TABLE device_buttons (
                mac TEXT NOT NULL REFERENCES devices(mac) ON DELETE CASCADE,
                position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 32),
                button_type TEXT NOT NULL CHECK(button_type IN ('line','speeddial','feature','empty')),
                line_extension TEXT REFERENCES lines(extension),
                button_label TEXT,
                option1 TEXT,
                option2 TEXT,
                PRIMARY KEY(mac, position)
            )
        """)
        connection.execute("""
            INSERT INTO device_buttons(mac,position,button_type,line_extension,button_label)
            SELECT mac,position,button_type,line_extension,line_extension
            FROM device_buttons_legacy
        """)
        connection.execute("DROP TABLE device_buttons_legacy")
    else:
        for column in ("button_label", "option1", "option2"):
            if column not in button_columns:
                connection.execute(f"ALTER TABLE device_buttons ADD COLUMN {column} TEXT")
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
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(devices)")}
    if "dhcp_address" not in columns:
        connection.execute("ALTER TABLE devices ADD COLUMN dhcp_address TEXT")
    # Migrate legacy single-line devices into normalized line and button records.
    for row in connection.execute("SELECT * FROM devices").fetchall():
        connection.execute(
            """INSERT OR IGNORE INTO lines
               (extension,label,description,context,cid_name,cid_num,updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            (row["extension"], row["label"], row["description"], row["context"],
             row["cid_name"], row["cid_num"], row["updated_at"])
        )
        connection.execute(
            "INSERT OR IGNORE INTO device_buttons(mac,position,button_type,line_extension) VALUES (?,1,'line',?)",
            (row["mac"], row["extension"])
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS devices_dhcp_address_unique "
        "ON devices(dhcp_address) WHERE dhcp_address IS NOT NULL"
    )
    connection.commit()
    try:
        # On FreePBX, the web application runs as the asterisk account. Keep
        # the same SQLite database writable by that account and root CLI users.
        # Other environments retain owner-only permissions.
        if os.geteuid() == 0:
            try:
                account = pwd.getpwnam("asterisk")
                group = grp.getgrnam("asterisk")
            except KeyError:
                os.chmod(path, 0o600)
            else:
                os.chown(path.parent, account.pw_uid, group.gr_gid)
                os.chmod(path.parent, 0o750)
                os.chown(path, account.pw_uid, group.gr_gid)
                os.chmod(path, 0o660)
        elif os.access(path.parent, os.W_OK):
            os.chmod(path, 0o660)
    except OSError:
        connection.close()
        raise
    return connection


def validate_dhcp_address(value):
    if value is None or value == "":
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ManagerError("--dhcp-address must be a valid IPv4 address") from exc
    if address.version != 4 or address.is_unspecified or address.is_multicast:
        raise ManagerError("--dhcp-address must be a usable IPv4 address")
    return str(address)


def export_dhcp_reservations(db, output, fmt, force):
    rows = db.execute(
        "SELECT mac, description, dhcp_address FROM devices "
        "WHERE dhcp_address IS NOT NULL ORDER BY dhcp_address"
    ).fetchall()
    if not rows:
        raise ManagerError("no devices have a DHCP address; set --dhcp-address first")
    lines = ["# TomOS SCCP DHCP reservations (generated; review before importing).",
             "# Export only: this file is not installed or activated automatically."]
    if fmt == "dnsmasq":
        lines.append("# Add to the dnsmasq configuration for the phone/voice network.")
        for row in rows:
            mac = ":".join(row["mac"][i:i + 2].lower() for i in range(0, 12, 2))
            lines.append("dhcp-host=" + mac + "," + row["dhcp_address"])
    else:
        lines.append("# Add these host declarations inside the matching subnet scope.")
        for row in rows:
            mac = ":".join(row["mac"][i:i + 2].lower() for i in range(0, 12, 2))
            name = "tomos-phone-" + row["mac"].lower()
            lines.extend(["host " + name + " {",
                          "  hardware ethernet " + mac + ";",
                          "  fixed-address " + row["dhcp_address"] + ";", "}"])
    destination = pathlib.Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not force:
            raise ManagerError("output already exists: " + str(destination) + "; use --force to back it up")
        backup = pathlib.Path(str(destination) + ".tomos-backup")
        if backup.exists():
            raise ManagerError("backup already exists: " + str(backup))
        import shutil
        shutil.copy2(destination, backup)
    fd, temporary = tempfile.mkstemp(prefix=".tomos-dhcp-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Exported " + str(len(rows)) + " DHCP reservation(s) to " + str(destination) + " (" + fmt + "); active DHCP was not changed.")

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
    dhcp_address = validate_dhcp_address(args.dhcp_address)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db:
            db.execute(
                """INSERT INTO devices
                   (mac, vendor_slug, model_number, template_family, description,
                    extension, label, cid_name, cid_num, context, created_at, updated_at,
                    dhcp_address)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (mac, vendor, model, family, description, extension, label,
                 cid_name, cid_num, context, now, now, dhcp_address)
            )
    except sqlite3.IntegrityError as exc:
        raise ManagerError(f"could not add device (duplicate MAC or unknown vendor/template): {exc}") from exc
    with db:
        db.execute("INSERT OR IGNORE INTO lines VALUES (?,?,?,?,?,?,?)",
                   (extension, label, description, context, cid_name, cid_num, now))
        db.execute("INSERT OR IGNORE INTO device_buttons(mac,position,button_type,line_extension,button_label) VALUES (?,1,'line',?,?)", (mac, extension, extension))
    print(f"Added {vendor} {model} phone SEP{mac} on extension {extension}.")



def update_device(db, args):
    mac = args.mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    row = db.execute("SELECT * FROM devices WHERE mac = ?", (mac,)).fetchone()
    if row is None:
        raise ManagerError(f"phone not found: {mac}")
    values = {
        "vendor_slug": args.vendor or row["vendor_slug"],
        "model_number": args.model or row["model_number"],
        "template_family": args.template_family or row["template_family"],
        "extension": args.extension or row["extension"],
        "description": args.description if args.description is not None else row["description"],
        "label": args.label if args.label is not None else row["label"],
        "cid_name": args.cid_name if args.cid_name is not None else row["cid_name"],
        "cid_num": args.cid_num if args.cid_num is not None else row["cid_num"],
        "context": args.context or row["context"],
        "dhcp_address": (validate_dhcp_address(args.dhcp_address)
                         if args.dhcp_address is not None else row["dhcp_address"]),
    }
    if values["vendor_slug"] not in VENDORS:
        raise ManagerError(f"unsupported vendor: {values['vendor_slug']}")
    if not MODEL_RE.fullmatch(values["model_number"]):
        raise ManagerError("--model must be a 3- or 4-digit SCCP device type")
    if values["template_family"] not in TEMPLATE_FAMILIES:
        raise ManagerError(f"unsupported Cisco template family: {values['template_family']}")
    validate_model_template(values["model_number"], values["template_family"])
    if not EXT_RE.fullmatch(values["extension"]):
        raise ManagerError("--extension must contain 1–20 digits")
    if not CONTEXT_RE.fullmatch(values["context"]):
        raise ManagerError("--context may contain only letters, digits, dot, underscore and hyphen")
    for key in ("description", "label", "cid_name"):
        values[key] = clean_text(values[key], key.replace("_", " "))
    values["cid_num"] = clean_text(values["cid_num"], "cid_num", 40)
    values["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        with db:
            db.execute("INSERT OR IGNORE INTO lines VALUES (?,?,?,?,?,?,?)",
                       (values["extension"], values["label"], values["description"],
                        values["context"], values["cid_name"], values["cid_num"], values["updated_at"]))
            db.execute(
                """UPDATE devices SET vendor_slug = :vendor_slug, model_number = :model_number,
                   template_family = :template_family, extension = :extension,
                   description = :description, label = :label, cid_name = :cid_name,
                   cid_num = :cid_num, context = :context, updated_at = :updated_at,
                   dhcp_address = :dhcp_address
                   WHERE mac = :mac""",
                {**values, "mac": mac}
            )
            button = db.execute("SELECT line_extension FROM device_buttons WHERE mac=? AND position=1",
                                (mac,)).fetchone()
            if button is None:
                db.execute("INSERT INTO device_buttons(mac,position,button_type,line_extension,button_label) VALUES (?,1,'line',?,?)", (mac, values["extension"], values["extension"]))
            elif button["line_extension"] != row["extension"]:
                db.execute("UPDATE device_buttons SET line_extension=?,button_label=? WHERE mac=? AND position=1",
                           (values["extension"], values["extension"], mac))
            db.execute("UPDATE lines SET label=?,description=?,context=?,cid_name=?,cid_num=?,updated_at=? WHERE extension=?",
                       (values["label"], values["description"], values["context"], values["cid_name"],
                        values["cid_num"], values["updated_at"], values["extension"]))
    except sqlite3.IntegrityError as exc:
        raise ManagerError(f"could not update phone: {exc}") from exc
    print(f"Updated phone SEP{mac}.")


def list_devices(db, as_json=False):
    rows = db.execute(
        """SELECT mac, vendor_slug, model_number, template_family, extension, description,
                  label, cid_name, cid_num, context, dhcp_address, created_at, updated_at
           FROM devices ORDER BY mac"""
    ).fetchall()
    if as_json:
        records = [dict(row) for row in rows]
        for record in records:
            record["buttons"] = get_device_buttons(db, record["mac"])
            record["button_extensions"] = ",".join(item["line_extension"] for item in record["buttons"] if item["button_type"] == "line")
            record["button_display"] = [str(item["position"]) + ": " + item["button_type"] + " " + (item["button_label"] or item["line_extension"] or "") for item in record["buttons"]]
        print(json.dumps(records, ensure_ascii=True))
        return
    if not rows:
        print("No phones registered yet.")
        return
    print(f"{'MAC':14} {'VENDOR':8} {'MODEL':7} {'TEMPLATE':16} {'EXTENSION':12} DESCRIPTION")
    for row in rows:
        print(f"{row['mac']:14} {row['vendor_slug']:8} {row['model_number']:7} "
              f"{row['template_family']:16} {row['extension']:12} {row['description']}")


def show_device(db, mac, as_json=False):
    mac = mac.replace(":", "").replace("-", "").upper()
    row = db.execute("SELECT * FROM devices WHERE mac = ?", (mac,)).fetchone()
    if row is None:
        raise ManagerError(f"phone not found: {mac}")
    if as_json:
        record = dict(row)
        record["buttons"] = get_device_buttons(db, mac)
        record["button_extensions"] = ",".join(item["line_extension"] for item in record["buttons"] if item["button_type"] == "line")
        record["button_display"] = [str(item["position"]) + ": " + item["button_type"] + " " + (item["button_label"] or item["line_extension"] or "") for item in record["buttons"]]
        print(json.dumps(record, ensure_ascii=True))
        return
    for key in ("mac", "vendor_slug", "model_number", "template_family", "description",
                "extension", "label", "cid_name", "cid_num", "context", "dhcp_address",
                "created_at", "updated_at"):
        print(f"{key}: {row[key]}")



def get_device_buttons(db, mac):
    return [dict(row) for row in db.execute(
        "SELECT b.position,b.button_type,b.line_extension,b.button_label,b.option1,b.option2,"
        "l.label AS line_label,l.description AS line_description,l.context,l.cid_name,l.cid_num "
        "FROM device_buttons b LEFT JOIN lines l ON l.extension=b.line_extension "
        "WHERE b.mac=? ORDER BY b.position",
        (mac,)
    ).fetchall()]


def _button_label(value):
    label = clean_text(value, "button label", 40)
    if any(char in label for char in ('"', "'", ",", "\\")):
        raise ManagerError("button label must not contain quotes, commas or backslashes")
    return label


def _validate_button(button_type, label=None, option1=None, option2=None, line_extension=None):
    if button_type not in ("line", "speeddial", "feature", "empty"):
        raise ManagerError("button type must be line, speeddial, feature or empty")
    if button_type == "empty":
        if any(value for value in (label, option1, option2, line_extension)):
            raise ManagerError("empty buttons do not accept label or options")
        return {"button_type": "empty", "button_label": None,
                "line_extension": None, "option1": None, "option2": None}
    if button_type == "line":
        if not line_extension or not EXT_RE.fullmatch(line_extension):
            raise ManagerError("line buttons require a 1–20 digit line extension")
        if any(value for value in (option1, option2)):
            raise ManagerError("line buttons do not accept extra options")
        label = _button_label(label or line_extension)
    elif button_type == "speeddial":
        label = _button_label(label or "Speed dial")
        if not option1 or not re.fullmatch(r"[0-9*+(). -]{1,40}", option1):
            raise ManagerError("speed-dial destination must contain only dialable digits and common separators")
        if option2 and not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}@[A-Za-z0-9_.-]{1,80}", option2):
            raise ManagerError("BLF hint must use extension@context syntax")
    elif button_type == "feature":
        label = _button_label(label or "Feature")
        feature = (option1 or "").lower()
        supported = {
            "privacy": {"callpresent", "hint"},
            "cfwdall": {"number"},
            "cfwbusy": {"number"},
            "dnd": {"busy", "silent", ""},
            "monitor": {""},
            "parkinglot": {"parameter"},
            "devstate": {"parameter"},
        }
        if feature not in supported:
            raise ManagerError("unsupported feature; choose privacy, cfwdall, cfwbusy, DND, monitor, parkinglot or devstate")
        parameter = (option2 or "").lower()
        if parameter not in supported[feature]:
            raise ManagerError(f"invalid parameter for feature {feature}")
        if feature in ("cfwdall", "cfwbusy") and not re.fullmatch(r"[0-9*+]{1,40}", parameter):
            raise ManagerError("call-forward feature requires a dialable destination number")
        if feature in ("parkinglot", "devstate") and not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", parameter):
            raise ManagerError(f"{feature} requires a valid identifier")
        option1 = "DND" if feature == "dnd" else feature
        option2 = parameter or None
    return {"button_type": button_type, "button_label": label,
            "line_extension": line_extension if button_type == "line" else None,
            "option1": option1, "option2": option2}


def _insert_button(db, mac, position, button):
    db.execute(
        """INSERT INTO device_buttons
           (mac,position,button_type,line_extension,button_label,option1,option2)
           VALUES (?,?,?,?,?,?,?)""",
        (mac, position, button["button_type"], button["line_extension"],
         button["button_label"], button["option1"], button["option2"])
    )


def add_device_button(db, args):
    mac = args.mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    if db.execute("SELECT 1 FROM devices WHERE mac=?", (mac,)).fetchone() is None:
        raise ManagerError(f"phone not found: {mac}")
    button = _validate_button(args.type, args.label, args.option1, args.option2, args.line_extension)
    existing = [dict(row) for row in db.execute(
        "SELECT * FROM device_buttons WHERE mac=? ORDER BY position", (mac,)).fetchall()]
    count = len(existing)
    position = args.position if args.position is not None else count + 1
    if position < 1 or position > count + 1 or count >= 32:
        raise ManagerError(f"button position must be between 1 and {min(count + 1, 32)}; maximum 32 buttons")
    if position == 1 and button["button_type"] != "line":
        raise ManagerError("the first configured button must be a line button")
    if button["button_type"] == "line" and any(
            item["button_type"] == "line" and item["line_extension"] == button["line_extension"]
            for item in existing):
        raise ManagerError("that line extension is already assigned to this phone")
    existing.insert(position - 1, button)
    with db:
        if button["button_type"] == "line":
            now = datetime.now(timezone.utc).isoformat()
            ext = button["line_extension"]
            db.execute("INSERT OR IGNORE INTO lines VALUES (?,?,?,?,?,?,?)",
                       (ext, button["button_label"], button["button_label"], "from-internal-xfer", ext, ext, now))
        db.execute("DELETE FROM device_buttons WHERE mac=?", (mac,))
        for index, item in enumerate(existing, 1):
            _insert_button(db, mac, index, item)
        if existing[0]["button_type"] == "line":
            db.execute("UPDATE devices SET extension=?,updated_at=? WHERE mac=?",
                       (existing[0]["line_extension"], datetime.now(timezone.utc).isoformat(), mac))
    print(f"Added {button['button_type']} button at position {position} on SEP{mac}.")


def remove_device_button(db, args):
    mac = args.mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    existing = [dict(row) for row in db.execute(
        "SELECT * FROM device_buttons WHERE mac=? ORDER BY position", (mac,)).fetchall()]
    if args.position < 1 or args.position > len(existing):
        raise ManagerError(f"button position {args.position} not found on SEP{mac}")
    removed = existing.pop(args.position - 1)
    if removed["button_type"] == "line" and not any(item["button_type"] == "line" for item in existing):
        raise ManagerError("a phone must retain at least one line button")
    if existing and existing[0]["button_type"] != "line":
        raise ManagerError("the first configured button must remain a line button")
    with db:
        db.execute("DELETE FROM device_buttons WHERE mac=?", (mac,))
        for index, item in enumerate(existing, 1):
            _insert_button(db, mac, index, item)
        if existing:
            db.execute("UPDATE devices SET extension=?,updated_at=? WHERE mac=?",
                       (existing[0]["line_extension"], datetime.now(timezone.utc).isoformat(), mac))
    print(f"Removed button {args.position} from SEP{mac}.")


def set_device_buttons(db, mac, raw_extensions):
    mac = mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    device = db.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
    if device is None:
        raise ManagerError(f"phone not found: {mac}")
    extensions = [value.strip() for value in raw_extensions.split(",") if value.strip()]
    if not extensions or len(extensions) > 32 or len(set(extensions)) != len(extensions):
        raise ManagerError("provide 1–32 unique comma-separated line extensions")
    if any(not EXT_RE.fullmatch(value) for value in extensions):
        raise ManagerError("button extensions must contain 1–20 digits")
    now = datetime.now(timezone.utc).isoformat()
    existing_non_line = [dict(row) for row in db.execute(
        "SELECT * FROM device_buttons WHERE mac=? AND button_type!='line' ORDER BY position",
        (mac,)).fetchall()]
    if len(extensions) + len(existing_non_line) > 32:
        raise ManagerError("line buttons plus existing speed-dial/feature buttons exceed the 32-button limit")
    with db:
        for extension in extensions:
            db.execute("INSERT OR IGNORE INTO lines VALUES (?,?,?,?,?,?,?)",
                       (extension, extension, extension, device["context"], extension, extension, now))
        db.execute("DELETE FROM device_buttons WHERE mac=?", (mac,))
        ordered = [_validate_button("line", extension, line_extension=extension) for extension in extensions]
        ordered.extend(existing_non_line)
        for position, button in enumerate(ordered, 1):
            _insert_button(db, mac, position, button)
        db.execute("UPDATE devices SET extension=?,updated_at=? WHERE mac=?",
                   (extensions[0], now, mac))
    print(f"Saved {len(extensions)} line button(s) for SEP{mac}.")



def update_line(db, args):
    if not EXT_RE.fullmatch(args.extension):
        raise ManagerError("--extension must contain 1–20 digits")
    row = db.execute("SELECT * FROM lines WHERE extension=?", (args.extension,)).fetchone()
    if row is None:
        raise ManagerError(f"line not found: {args.extension}")
    values = {
        "label": clean_text(args.label, "--label") if args.label is not None else row["label"],
        "description": clean_text(args.description, "--description") if args.description is not None else row["description"],
        "context": args.context if args.context is not None else row["context"],
        "cid_name": clean_text(args.cid_name, "--cid-name") if args.cid_name is not None else row["cid_name"],
        "cid_num": clean_text(args.cid_num, "--cid-num", 40) if args.cid_num is not None else row["cid_num"],
    }
    if not CONTEXT_RE.fullmatch(values["context"]):
        raise ManagerError("--context contains invalid characters")
    now = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute("UPDATE lines SET label=?,description=?,context=?,cid_name=?,cid_num=?,updated_at=? WHERE extension=?",
                   (values["label"], values["description"], values["context"], values["cid_name"],
                    values["cid_num"], now, args.extension))
        db.execute("UPDATE devices SET label=?,description=?,context=?,cid_name=?,cid_num=?,updated_at=? WHERE extension=?",
                   (values["label"], values["description"], values["context"], values["cid_name"],
                    values["cid_num"], now, args.extension))
    print(f"Updated line {args.extension}.")


def preview_inventory(db):
    import contextlib
    import io
    with tempfile.TemporaryDirectory(prefix="tomos-sccp-preview-") as temporary:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            render_inventory(db, temporary, False)
        root = pathlib.Path(temporary)
        return {"files": {name: (root / name).read_text(encoding="utf-8")
                          for name in ("sccp_hardware.conf", "sccp_extensions.conf")},
                "summary": captured.getvalue().strip(),
                "device_count": db.execute("SELECT COUNT(*) FROM devices").fetchone()[0],
                "button_count": db.execute("SELECT COUNT(*) FROM device_buttons").fetchone()[0]}


def live_device_status(db, asterisk_bin):
    try:
        result = subprocess.run([asterisk_bin, "-rx", "sccp show devices"],
                                text=True, capture_output=True, check=False, timeout=10)
    except subprocess.TimeoutExpired as exc:
        raise ManagerError("Asterisk SCCP status command timed out after 10 seconds") from exc
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise ManagerError("Asterisk SCCP status command failed: " + output)
    records = []
    for device in db.execute("SELECT mac,extension,description FROM devices ORDER BY mac"):
        line = next((item for item in output.splitlines()
                     if device["mac"].lower() in item.lower()
                     or ("SEP" + device["mac"]).lower() in item.lower()), None)
        if line is None:
            state = "not-listed"
        elif re.search(r"\b(unregistered|offline|disconnected)\b", line, re.I):
            state = "unregistered"
        elif re.search(r"\b(registered|online|onhook|offhook)\b", line, re.I):
            state = "registered"
        else:
            state = "unknown"
        records.append({"mac": device["mac"], "extension": device["extension"],
                        "description": device["description"], "state": state, "detail": line or ""})
    return {"source": "asterisk -rx 'sccp show devices'", "devices": records, "raw": output,
            "note": "Unknown means the Asterisk output did not expose a recognised state."}


def remove_device(db, mac):
    mac = mac.replace(":", "").replace("-", "").upper()
    if not MAC_RE.fullmatch(mac):
        raise ManagerError("--mac must contain exactly 12 hexadecimal characters")
    with db:
        db.execute("DELETE FROM device_buttons WHERE mac = ?", (mac,))
        cursor = db.execute("DELETE FROM devices WHERE mac = ?", (mac,))
        db.execute("DELETE FROM lines WHERE extension NOT IN (SELECT line_extension FROM device_buttons)")
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
    hardware_path = pathlib.Path(output_dir) / "sccp_hardware.conf"
    hardware_text = hardware_path.read_text(encoding="utf-8")
    for row in rows:
        buttons = get_device_buttons(db, row["mac"])
        button_lines = []
        for button in buttons:
            kind = button["button_type"]
            if kind == "line":
                button_lines.append(f"button = line, {button['line_extension']}")
            elif kind == "speeddial":
                hint = f", {button['option2']}" if button["option2"] else ""
                button_lines.append(f'button = speeddial, "{button["button_label"]}", {button["option1"]}{hint}')
            elif kind == "feature":
                parameter = f", {button['option2']}" if button["option2"] else ""
                button_lines.append(f'button = feature, "{button["button_label"]}", {button["option1"]}{parameter}')
            elif kind == "empty":
                button_lines.append("button = empty")
        default_line = f"button = line, {row['extension']}"
        if button_lines:
            hardware_text = hardware_text.replace(default_line, "\n".join(button_lines), 1)
    hardware_path.write_text(hardware_text, encoding="utf-8")

    extension_path = pathlib.Path(output_dir) / "sccp_extensions.conf"
    extension_text = extension_path.read_text(encoding="utf-8")
    rendered_extensions = {row["extension"] for row in rows}
    all_lines = db.execute(
        "SELECT * FROM lines WHERE extension IN (SELECT line_extension FROM device_buttons) ORDER BY extension"
    ).fetchall()
    for line in all_lines:
        if line["extension"] in rendered_extensions:
            continue
        extension_text += (
            f"\n[{line['extension']}]\ntype = line\nid = 1\n"
            f"label = {line['label']}\ndescription = {line['description']}\n"
            f"context = {line['context']}\ncid_name = {line['cid_name']}\n"
            f"cid_num = {line['cid_num']}\n"
        )
    extension_path.write_text(extension_text, encoding="utf-8")
    print(f"Managed inventory: {len(rows)} phone(s).")



def export_sep_configs(db, args):
    """Render every inventory phone into a reviewed, non-live TFTP export."""
    rows = db.execute(
        "SELECT mac, vendor_slug, template_family FROM devices ORDER BY mac"
    ).fetchall()
    if not rows:
        raise ManagerError("inventory is empty; add at least one phone before SEP export")
    helper = pathlib.Path(__file__).with_name("tomos-sccp-sep.py")
    if not helper.is_file():
        raise ManagerError(f"existing Cisco SEP renderer is missing: {helper}")
    template_dir = pathlib.Path(args.template_dir)
    if not template_dir.is_dir():
        raise ManagerError(f"Cisco template directory does not exist: {template_dir}")
    destination = pathlib.Path(args.output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    targets = [destination / f"SEP{row['mac']}.cnf.xml" for row in rows]
    manifest_path = destination / "tomos-sccp-sep-manifest.json"
    manifest_backup = pathlib.Path(str(manifest_path) + ".tomos-backup")
    if manifest_path.exists() and not args.force:
        raise ManagerError(f"refusing to overwrite {manifest_path}; use --force to preserve a backup")
    if manifest_path.exists() and manifest_backup.exists():
        raise ManagerError(f"backup already exists: {manifest_backup}")
    for target in targets:
        if target.exists() and not args.force:
            raise ManagerError(f"refusing to overwrite {target}; use --force to preserve backups")
        backup = target.with_name(target.name + ".tomos-backup")
        if target.exists() and backup.exists():
            raise ManagerError(f"backup already exists: {backup}; move it before using --force")

    import shutil
    import xml.etree.ElementTree as ET
    committed = []
    backups = []
    try:
        with tempfile.TemporaryDirectory(prefix="tomos-sccp-sep-export-",
                                         dir=str(destination)) as temporary:
            staged = pathlib.Path(temporary)
            for row, target in zip(rows, targets):
                if row["vendor_slug"] != "cisco":
                    raise ManagerError(f"unsupported SEP export vendor for {row['mac']}: {row['vendor_slug']}")
                staged_file = staged / target.name
                command = [
                    sys.executable, str(helper),
                    "--model", row["template_family"],
                    "--mac", row["mac"],
                    "--pbx-address", args.pbx_address,
                    "--port", str(args.port),
                    "--template-dir", str(template_dir),
                    "--output", str(staged_file),
                ]
                if args.ntp_server:
                    command.extend(["--ntp-server", args.ntp_server])
                result = subprocess.run(command, text=True, capture_output=True, check=False)
                if result.returncode:
                    detail = result.stderr.strip() or result.stdout.strip() or "SEP renderer failed"
                    raise ManagerError(f"could not render SEP{row['mac']}.cnf.xml: {detail}")
                try:
                    ET.parse(staged_file)
                except (ET.ParseError, OSError) as exc:
                    raise ManagerError(f"invalid staged XML for SEP{row['mac']}: {exc}") from exc

            # Pre-render every phone before touching any destination file.
            for target in targets:
                if target.exists():
                    backup = target.with_name(target.name + ".tomos-backup")
                    shutil.copy2(target, backup)
                    backups.append((target, backup))
            for target in targets:
                os.replace(staged / target.name, target)
                committed.append(target)
    except Exception:
        for target in reversed(committed):
            backup = next((b for t, b in backups if t == target), None)
            if backup and backup.exists():
                shutil.copy2(backup, target)
            elif target.exists():
                target.unlink()
        for _, backup in backups:
            if backup.exists():
                backup.unlink()
        raise

    import hashlib
    manifest = {
        "schema_version": 1,
        "pbx_address": str(ipaddress.IPv4Address(args.pbx_address)),
        "sccp_port": args.port,
        "files": [
            {"mac": row["mac"], "template_family": row["template_family"],
             "filename": target.name,
             "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
            for row, target in zip(rows, targets)
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if manifest_path.exists():
        import shutil
        shutil.copy2(manifest_path, manifest_backup)
    fd, temporary_manifest = tempfile.mkstemp(prefix=".tomos-sep-manifest-", dir=str(destination))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(manifest_bytes)
        os.chmod(temporary_manifest, 0o600)
        os.replace(temporary_manifest, manifest_path)
    finally:
        if os.path.exists(temporary_manifest):
            os.unlink(temporary_manifest)
    approval = hashlib.sha256(manifest_bytes).hexdigest()
    print(f"Exported and XML-validated {len(rows)} Cisco SEP file(s) to {destination}.")
    print(f"Review all XML files, then approve this exact manifest for deployment with SHA-256: {approval}")
    print("No live TFTP files, DHCP, Asterisk or phones were changed.")


def deploy_sep_configs(args):
    """Deploy only a reviewed SEP export whose manifest hash was approved."""
    import hashlib
    import shutil
    import xml.etree.ElementTree as ET

    staging = pathlib.Path(args.staging_dir).resolve()
    tftp_root = pathlib.Path(args.tftp_root).resolve()
    manifest_path = staging / "tomos-sccp-sep-manifest.json"
    if not staging.is_dir() or not tftp_root.is_dir():
        raise ManagerError("staging directory and existing TFTP root must both exist")
    if staging == tftp_root or staging in tftp_root.parents or tftp_root in staging.parents:
        raise ManagerError("staging directory and TFTP root must be separate directories")
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ManagerError("review manifest is missing or is not a regular file")
    raw_manifest = manifest_path.read_bytes()
    actual_approval = hashlib.sha256(raw_manifest).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}", args.approve_sha256 or ""):
        raise ManagerError("deployment requires --approve-sha256 with the reviewed manifest hash")
    if actual_approval != args.approve_sha256:
        raise ManagerError("manifest approval hash does not match; review the current export again")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManagerError(f"invalid SEP export manifest: {exc}") from exc
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list) or not manifest["files"]:
        raise ManagerError("unsupported or empty SEP export manifest")
    filenames = set()
    sources = []
    for entry in manifest["files"]:
        filename, mac, digest = entry.get("filename", ""), entry.get("mac", ""), entry.get("sha256", "")
        if not MAC_RE.fullmatch(mac) or filename != f"SEP{mac}.cnf.xml":
            raise ManagerError("manifest contains an invalid Cisco SEP filename or MAC")
        if filename in filenames or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ManagerError("manifest contains duplicate filenames or invalid SHA-256 values")
        filenames.add(filename)
        source = staging / filename
        if source.is_symlink() or not source.is_file():
            raise ManagerError(f"staged SEP file is missing or not a regular file: {filename}")
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ManagerError(f"staged SEP file changed since review: {filename}")
        try:
            ET.parse(source)
        except ET.ParseError as exc:
            raise ManagerError(f"staged SEP file is not valid XML: {filename}: {exc}") from exc
        sources.append((source, tftp_root / filename))

    backups = []
    committed = []
    with tempfile.TemporaryDirectory(prefix=".tomos-sccp-deploy-", dir=str(tftp_root)) as temp:
        prepared = pathlib.Path(temp)
        for source, target in sources:
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise ManagerError(f"refusing to replace non-regular TFTP target: {target}")
            backup = pathlib.Path(str(target) + ".tomos-backup")
            if target.exists() and not args.force:
                raise ManagerError(f"refusing to overwrite {target}; use --force after reviewing its backup")
            if target.exists() and backup.exists():
                raise ManagerError(f"backup already exists: {backup}; move it before deployment")
            shutil.copyfile(source, prepared / target.name)
            os.chmod(prepared / target.name, 0o644)
        try:
            for _, target in sources:
                if target.exists():
                    backup = pathlib.Path(str(target) + ".tomos-backup")
                    shutil.copy2(target, backup)
                    backups.append((target, backup))
            for _, target in sources:
                os.replace(prepared / target.name, target)
                committed.append(target)
        except Exception:
            for target in reversed(committed):
                backup = next((b for t, b in backups if t == target), None)
                if backup and backup.exists():
                    shutil.copy2(backup, target)
                elif target.exists():
                    target.unlink()
            for _, backup in backups:
                if backup.exists():
                    backup.unlink()
            raise

    print(f"Deployed {len(sources)} reviewed Cisco SEP file(s) to {tftp_root}.")
    print("Existing files were backed up where replaced. No TFTP service reload or handset restart was performed.")

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
    add.add_argument("--dhcp-address", help="optional static IPv4 address for DHCP reservation export")
    update = device_sub.add_parser("update")
    update.add_argument("--mac", required=True)
    update.add_argument("--vendor", choices=tuple(VENDORS))
    update.add_argument("--model")
    update.add_argument("--template-family", choices=tuple(TEMPLATE_FAMILIES))
    update.add_argument("--extension")
    update.add_argument("--description")
    update.add_argument("--label")
    update.add_argument("--cid-name")
    update.add_argument("--cid-num")
    update.add_argument("--context")
    update.add_argument("--dhcp-address", help="set static IPv4 address; pass empty value to clear")
    listing = device_sub.add_parser("list")
    listing.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    show = device_sub.add_parser("show")
    show.add_argument("--mac", required=True)
    show.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    remove = device_sub.add_parser("remove")
    remove.add_argument("--mac", required=True)
    remove.add_argument("--confirm", action="store_true",
                        help="confirm removing the device from the inventory")

    buttons = device_sub.add_parser("buttons", help="configure line buttons for a phone")
    buttons.add_argument("--mac", required=True)
    buttons.add_argument("--extensions", required=True, help="comma-separated line extensions in button order")
    button_add = device_sub.add_parser("button-add", help="add a line, speed-dial, feature or empty button")
    button_add.add_argument("--mac", required=True)
    button_add.add_argument("--position", type=int)
    button_add.add_argument("--type", choices=("line", "speeddial", "feature", "empty"), required=True)
    button_add.add_argument("--label")
    button_add.add_argument("--line-extension")
    button_add.add_argument("--option1", help="speed-dial number or feature type")
    button_add.add_argument("--option2", help="optional BLF hint or feature parameter")
    button_remove = device_sub.add_parser("button-remove", help="remove a button by position")
    button_remove.add_argument("--mac", required=True)
    button_remove.add_argument("--position", type=int, required=True)

    line = sub.add_parser("line", help="manage shared line configuration")
    line_sub = line.add_subparsers(dest="action", required=True)
    line_update = line_sub.add_parser("update")
    line_update.add_argument("--extension", required=True)
    line_update.add_argument("--label")
    line_update.add_argument("--description")
    line_update.add_argument("--context")
    line_update.add_argument("--cid-name")
    line_update.add_argument("--cid-num")

    preview = sub.add_parser("preview", help="create a temporary provisioning preview")
    status = sub.add_parser("status", help="read live SCCP handset state from Asterisk")
    status.add_argument("--asterisk-bin", default=os.environ.get("ASTERISK_BIN", "/usr/sbin/asterisk"))

    render = sub.add_parser("render", help="render managed inventory to staging include files")
    render.add_argument("--output-dir", required=True)
    render.add_argument("--force", action="store_true")

    dhcp = sub.add_parser("dhcp-export", help="export static DHCP reservations (does not change DHCP service)")
    dhcp.add_argument("--format", choices=("dnsmasq", "isc-dhcpd"), required=True)
    dhcp.add_argument("--output", required=True)
    dhcp.add_argument("--force", action="store_true")

    sep = sub.add_parser("sep-export", help="render per-phone Cisco SEP XML from inventory into a reviewed TFTP staging directory")
    sep.add_argument("--pbx-address", required=True, help="phone-reachable PBX IPv4 address")
    sep.add_argument("--port", type=int, default=2000)
    sep.add_argument("--ntp-server", help="optional NTP server IPv4 address")
    sep.add_argument("--template-dir", default="/usr/share/tomos-sccp/tftp-templates")
    sep.add_argument("--output-dir", required=True, help="staging directory; not the live TFTP root")
    sep.add_argument("--force", action="store_true", help="back up existing SEP files before replacing them")

    deploy = sub.add_parser("sep-deploy", help="deploy only a reviewed SEP export into an existing TFTP root")
    deploy.add_argument("--staging-dir", required=True)
    deploy.add_argument("--tftp-root", required=True)
    deploy.add_argument("--approve-sha256", required=True,
                        help="SHA-256 printed by sep-export after reviewing the manifest")
    deploy.add_argument("--force", action="store_true",
                        help="back up existing TFTP files before replacing them")

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
            elif args.action == "update":
                update_device(db, args)
            elif args.action == "buttons":
                set_device_buttons(db, args.mac, args.extensions)
            elif args.action == "button-add":
                add_device_button(db, args)
            elif args.action == "button-remove":
                remove_device_button(db, args)
            elif args.action == "list":
                list_devices(db, args.json)
            elif args.action == "show":
                show_device(db, args.mac, args.json)
            elif args.action == "remove":
                if not args.confirm:
                    raise ManagerError("removal requires --confirm")
                remove_device(db, args.mac)
        elif args.command == "line":
            if args.action == "update":
                update_line(db, args)
        elif args.command == "preview":
            print(json.dumps(preview_inventory(db), ensure_ascii=True))
        elif args.command == "status":
            print(json.dumps(live_device_status(db, args.asterisk_bin), ensure_ascii=True))
        elif args.command == "render":
            render_inventory(db, args.output_dir, args.force)
        elif args.command == "dhcp-export":
            export_dhcp_reservations(db, args.output, args.format, args.force)
        elif args.command == "sep-export":
            export_sep_configs(db, args)
        elif args.command == "sep-deploy":
            deploy_sep_configs(args)
        return 0
    except (ManagerError, OSError, sqlite3.Error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    finally:
        if db is not None:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
