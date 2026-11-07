# TomOS SCCP for FreePBX 17

TomOS SCCP is a FreePBX 17 / Debian 12 integration and provisioning layer built around the original [chan-sccp/chan-sccp](https://github.com/chan-sccp/chan-sccp) Asterisk channel driver. TomOS does not reimplement the SCCP protocol.

> **Development status:** early integration release. CI and static tests do not replace testing on a real FreePBX 17 system and physical Cisco phones. Back up the PBX and test on a staging host before production use.

## What TomOS adapts from chan-sccp

- Builds the original upstream driver from source against the installed Asterisk headers.
- Enables upstream conference support; experimental options are deliberately not enabled by default.
- Preserves upstream SCCP configuration examples and Cisco TFTP model templates under `/usr/share/tomos-sccp`.
- Provides a separate, opt-in TFTP template deployment command that never overwrites existing files.
- Manages only the TomOS-owned block in `/etc/asterisk/modules.conf`.
- Backs up the existing driver and module configuration before installation.
- Installs read-only Asterisk/SCCP diagnostics.
- Records the exact upstream Git commit used for the build.

See [the upstream adaptation notes](docs/UPSTREAM-ADAPTATION.md) for the source-to-TomOS mapping and licensing approach.

## One-line installation

Review the installer before running it. On a supported FreePBX 17 / Debian 12 host:

```bash
curl -fsSL https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main/install-stack.sh | sudo bash
```

The default full-stack command installs the channel driver, TomOS support assets and the native **TomOS SCCP Manager** FreePBX module. Open **Admin → TomOS SCCP** in FreePBX to add, edit and remove Cisco handset inventory. The web page calls the same TomOS manager and SQLite database used by the CLI; it does not maintain a separate phone inventory. Changes are immediately shared between the two interfaces. The module currently manages the phone inventory fields supported by TomOS; advanced softkey/button and line-feature editing is not yet included. Back up the PBX and validate on a staging system before production use. To install only the driver and CLI tools, explicitly opt out with `TOMOS_SCCP_INSTALL_MANAGER=0`.

Driver-only installation:

```bash
curl -fsSL https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main/install.sh | sudo bash
```

The driver source ref can be selected with `TOMOS_SCCP_REF`; the default is upstream `develop`.

## Compatibility and requirements

- FreePBX 17 on Debian 12.
- A running Asterisk 18–23 instance.
- Development headers matching the running Asterisk build. Upstream `./configure` detects and validates the PBX build environment.
- Network access to Debian package repositories and GitHub.
- An Asterisk service account named `asterisk`.
- A verified PBX backup.

If configuration fails, install the vendor-matched Asterisk development package for the exact PBX build and retry.

The upstream driver documents these required Asterisk modules: `app_voicemail`, `bridge_simple`, `bridge_native_rtp`, `bridge_softmix`, `bridge_holding`, `res_stasis` and `res_stasis_device_state`. TomOS checks that they can be loaded before replacing the active driver.

## Cisco provisioning templates

The installer stages upstream configuration examples in:

- `/usr/share/tomos-sccp/examples/`
- `/usr/share/tomos-sccp/tftp-templates/`

No example SCCP configuration is copied over `/etc/asterisk/sccp.conf`. The upstream sample files contain example device entries, PINs and hotline settings; review and replace these before use.

To copy only missing template files into an existing TFTP root:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-install-tftp-templates.sh --tftp-root /srv/tftp
```

Change `/srv/tftp` to the TFTP root configured on your PBX. Existing template files are preserved. This command does not install or reconfigure a TFTP daemon, DHCP option 150, phone firmware or firewall rules.

## Cisco phone DHCP provisioning

Cisco phones need a reachable TFTP server address. TomOS provides example DHCP snippets for existing DHCP services; it does not install, enable or take over a DHCP server.

- [dnsmasq example](examples/dhcp/dnsmasq.conf): sends Cisco DHCP Option 150 with the TomOS TFTP server IPv4 address.
- [ISC DHCP example](examples/dhcp/isc-dhcpd.conf): defines Option 150 as an array of IPv4 addresses and assigns it in the voice subnet. ISC DHCP is end-of-life; use this only when maintaining an existing deployment.

Edit the interface, voice subnet, lease pool, router, DNS and TFTP addresses before use. Keep the scope on the phone/voice VLAN and ensure there is only one authoritative DHCP service for that subnet. Option 150 can carry multiple TFTP server addresses; Option 66 is an alternative for a single server. The TFTP server must be reachable by the phones and UDP/TFTP traffic must be allowed by the network.

These files are examples, not drop-in replacements for a site's DHCP configuration. Back up the active DHCP configuration, merge the relevant settings into the existing server, validate it with that server's configuration checker, and reload it during a maintenance window. The installer does not modify DHCP configuration.

## Device and extension provisioning (staging only)

Create a JSON inventory based on [the example](examples/devices.example.json), then validate and render it:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-provision.py validate --input devices.json
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-provision.py render --input devices.json --output-dir /var/tmp/tomos-sccp-generated
```

The renderer validates Cisco MAC addresses, model-number syntax, extension numbers, Asterisk context names and config-safe text. It supports multiple phones sharing one line when their line settings match. It writes separate `sccp_hardware.conf` and `sccp_extensions.conf` include fragments into a staging directory; it does **not** edit live Asterisk configuration, create extensions in FreePBX, deploy per-phone XML, set DHCP/TFTP, or reload Asterisk. Review the generated files and confirm the dialplan context and FreePBX extension exist before manually integrating them. Existing output files are never overwritten unless `--force` is supplied; then a `.tomos-backup` copy is preserved.


## TomOS provisioning manager

TomOS now includes a native SQLite-backed provisioning manager, inspired by Endpoint Manager's separation of vendor, model/template and device inventory. It is the shared inventory engine used by both the native FreePBX web module and the TomOS CLI, and it does not copy Endpointman's code.

Initial support is limited to Cisco SCCP phones and the model-template families supplied by upstream chan-sccp. The catalogue is local; it does not rely on Endpointman's legacy remote provider catalogue.

```bash
# Create the inventory database and inspect supported catalogues
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py init
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py vendor list
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py model list

# Register a Cisco phone
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py device add \
  --mac 001122AABBCC \
  --vendor cisco \
  --model 7960 \
  --template-family 7940_7960 \
  --extension 1000 \
  --description "Front desk"

# Update a phone
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py device update --mac 001122AABBCC --description "Main reception"

# List and inspect the inventory
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py device list
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py device show --mac 001122AABBCC

# Render Asterisk SCCP include fragments into a staging directory
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py render \
  --output-dir /var/tmp/tomos-sccp-generated
```

The inventory database defaults to `/var/lib/tomos-sccp/provisioning.db`; override it with `--database` or `TOMOS_SCCP_DB`. The database directory is restricted to the asterisk account and the database file is group-readable/writable only by the asterisk group so the FreePBX GUI and root CLI share it. Device removal requires `--confirm`. Rendering delegates to the existing tested SCCP renderer and never edits live Asterisk or TFTP configuration. The current renderer requires all devices in one render to share the same dialplan context. Phone model numbers and template-family selections must be checked against the physical handset and firmware; the template family is not an automatic firmware compatibility guarantee.

### Export static DHCP reservations from the phone inventory

When adding or updating a phone, optionally assign a reserved IPv4 address. This is inventory metadata only; it does not request or change a lease on the live DHCP server:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py device add \
  --mac 001122AABBCC --model 7960 --template-family 7940_7960 \
  --extension 1000 --description "Front desk" --dhcp-address 192.168.10.50

# Export reservations for review and manual inclusion in dnsmasq:
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py dhcp-export \
  --format dnsmasq --output /var/tmp/tomos-phones.conf

# Or export ISC dhcpd host declarations:
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py dhcp-export \
  --format isc-dhcpd --output /var/tmp/tomos-phones-isc.conf
```

Only devices with `--dhcp-address` are exported. Addresses must be unique IPv4 addresses. The exporter refuses to overwrite an existing file unless `--force` is supplied; force mode preserves a `.tomos-backup` copy and refuses to overwrite an existing backup. Generated files are owner-readable only. ISC declarations must be placed inside the matching subnet scope. Review the output and check for conflicts with existing leases/reservations before manually merging it into your DHCP server. TomOS does not install, reload or modify the active DHCP service.

## Cisco phone TFTP call-manager configuration

Generate the Cisco XMLDefault.cnf.xml call-manager target file using the PBX address that phones can actually reach:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-tftp.py \
  --pbx-address 192.168.10.5 \
  --port 2000 \
  --output /var/tmp/XMLDefault.cnf.xml
```

To deploy directly into an existing TFTP root, use --output /srv/tftp --deploy. An optional --backup-pbx-address adds a second call-manager entry. Existing files are preserved unless --force is supplied, which first saves a .tomos-backup copy. The generated XML intentionally contains no firmware load strings: firmware varies by Cisco model and must be selected and tested separately. The tool does not configure DHCP option 150 or install a TFTP daemon.

Generate a per-phone SEP file from one of the upstream model templates staged by the installer (supported families: 69xx, 791x, 7925, 7937, 7940/7960, 796x, 797x and 797x extended):

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-sep.py \\
  --model 796x \\
  --mac 001122AABBCC \\
  --pbx-address 192.168.10.5 \\
  --output /var/tmp/SEP001122AABBCC.cnf.xml
```

Use `--output /srv/tftp --deploy` to write the correctly named `SEP<MAC>.cnf.xml` into an existing TFTP root. The renderer substitutes the PBX address placeholders, removes the upstream sample NTP server unless `--ntp-server` is supplied, and preserves existing files unless `--force` is supplied. The renderer removes the upstream `cisco`/`cisco` SSH credentials by default. If phone SSH access is required, provide `--ssh-user` and `--ssh-password-file` pointing to a file protected with mode `0600`; the password is not placed in shell history or process arguments. Model templates are upstream examples, not a guarantee that every firmware/model combination will register; validate on the target handset before rollout.


### Export per-phone SEP XML from the manager inventory

Generate one Cisco `SEP<MAC>.cnf.xml` file per registered phone, using the template family selected for that device:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py sep-export \
  --pbx-address 192.168.10.5 \
  --output-dir /var/tmp/tomos-sccp-tftp-review
```

This is a reviewed staging export, not a live deployment. The manager first renders and parses every phone's XML in a temporary directory; it writes nothing to the destination if a template is missing or any phone fails validation. Existing files are refused unless `--force` is supplied, which preserves `.tomos-backup` copies and rolls back a partial export if a write fails. Optional `--template-dir`, `--port` and `--ntp-server` settings are available. Review the XML and confirm handset model and firmware compatibility before manually copying files to the configured TFTP root. DHCP, live TFTP files, Asterisk and phones are not changed.


### Deploy a reviewed SEP export to TFTP

After `sep-export` finishes, inspect every XML file and the manifest. It prints the manifest SHA-256 approval value. Only after reviewing those exact files, deploy them into an existing TFTP root:

```bash
sha256sum /var/tmp/tomos-sccp-tftp-review/tomos-sccp-sep-manifest.json
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-manager.py sep-deploy \
  --staging-dir /var/tmp/tomos-sccp-tftp-review \
  --tftp-root /srv/tftp \
  --approve-sha256 REPLACE_WITH_REVIEWED_SHA256
```

Deployment rechecks the approval hash, each staged file's SHA-256 and XML validity, and refuses symlinks, non-regular targets and existing TFTP files by default. Add `--force` only when replacing files is intentional; previous files are copied to `.tomos-backup` and a partial deployment is rolled back on failure. Staging and TFTP directories must be separate. This copies files only: it does not reload TFTP, change DHCP/Asterisk, or reboot phones. Test handset retrieval and registration manually before production use.

## Physical Cisco handset validation

Use the [handset validation runbook](docs/HANDSET-VALIDATION.md) to record TFTP retrieval, registration, incoming/outgoing calls, two-way audio and model/firmware results. The read-only PBX snapshot helper prints Asterisk's SCCP device and line status plus recent service logs:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-phone-check.sh \
  --mac 001122AABBCC --extension 1000
```

It does not change the PBX or place calls. Compare the actual device and line state in its output; a configured entry alone is not proof of registration. Physical handset and call testing remain manual acceptance tests.

## Diagnostics

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-doctor.sh
sudo asterisk -rx 'module show like chan_sccp.so'
sudo asterisk -rx 'sccp show devices'
sudo asterisk -rx 'sccp show lines'
sudo journalctl -u asterisk -n 100
```

## FreePBX module loading

TomOS manages only its marked block in `/etc/asterisk/modules.conf`, excluding Asterisk's competing `chan_skinny.so` and loading `chan_sccp.so`. FreePBX may regenerate this file, so verify module loading after applying configuration and after upgrades.

## FreePBX web GUI manager

The default stack installer installs the native `tomos_sccp` FreePBX module. Open **Admin → TomOS SCCP** to manage Cisco phone inventory. The page invokes the installed `tomos-sccp-manager.py` command and reads/writes the same `/var/lib/tomos-sccp/provisioning.db` SQLite database used by CLI commands:

- Add, edit and remove phones from the FreePBX page.
- View model, template family, extension, description and optional DHCP reservation.
- Continue using `tomos-sccp-manager.py device add/update/list/show/remove` from a shell; both interfaces operate on the same records.
- The database is owned by the FreePBX `asterisk` account/group with non-world-readable permissions so the authenticated FreePBX page can update it.

The initial GUI milestone covers shared device inventory CRUD. It does not yet expose every advanced driver feature (for example button/softkey layouts), nor does it automatically apply generated files to live Asterisk or TFTP. Rendering and deployment remain explicit CLI workflows. The older Nortien `sccp_manager` module is no longer installed by the default TomOS installer; if it is already present on a PBX, do not use both modules to manage the same phones. Back up the PBX before installing and validate on a staging host.

## Tests

```bash
bash -n install.sh
bash -n install-stack.sh
bash -n install-manager.sh
bash -n scripts/tomos-sccp-doctor.sh
bash -n scripts/tomos-sccp-install-tftp-templates.sh
bash tests/test-installer-static.sh
bash tests/test-dhcp-examples.sh
bash tests/test-tftp-templates.sh
python3 tests/test-modules-conf.py
python3 tests/test-sccp-provision.py
python3 tests/test-sccp-tftp.py
```

GitHub Actions runs ShellCheck, syntax checks, static checks, module-configuration idempotence tests and safe TFTP template deployment and SCCP provisioning and Cisco TFTP XML generation tests.

## Upstream and licensing

The SCCP channel driver and its configuration/template assets are maintained by the [chan-sccp project](https://github.com/chan-sccp/chan-sccp). TomOS downloads and builds that upstream source at install time; it does not claim authorship of the driver or relicense upstream files. See the upstream `COPYING` and `LICENSE` files for the driver's terms.

TomOS-specific installer and helper scripts are MIT-licensed; see [LICENSE](LICENSE). Third-party components retain their own licences.
