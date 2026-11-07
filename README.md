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

The default full-stack command installs the channel driver and TomOS support assets. It does **not** install a GUI manager by default because compatibility between the optional manager fork and the original upstream driver still needs integration testing.

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

## Device and extension provisioning (staging only)

Create a JSON inventory based on [the example](examples/devices.example.json), then validate and render it:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-provision.py validate --input devices.json
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-provision.py render --input devices.json --output-dir /var/tmp/tomos-sccp-generated
```

The renderer validates Cisco MAC addresses, model-number syntax, extension numbers, Asterisk context names and config-safe text. It supports multiple phones sharing one line when their line settings match. It writes separate `sccp_hardware.conf` and `sccp_extensions.conf` include fragments into a staging directory; it does **not** edit live Asterisk configuration, create extensions in FreePBX, deploy per-phone XML, set DHCP/TFTP, or reload Asterisk. Review the generated files and confirm the dialplan context and FreePBX extension exist before manually integrating them. Existing output files are never overwritten unless `--force` is supplied; then a `.tomos-backup` copy is preserved.

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

Use `--output /srv/tftp --deploy` to write the correctly named `SEP<MAC>.cnf.xml` into an existing TFTP root. The renderer substitutes the PBX address placeholders, removes the upstream sample NTP server unless `--ntp-server` is supplied, and preserves existing files unless `--force` is supplied. Model templates are upstream examples, not a guarantee that every firmware/model combination will register; validate on the target handset before rollout.

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

## Optional GUI manager

An optional manager installer remains available separately, but it currently targets the Nortien SCCP Manager fork. It is **not enabled by default** and must not be treated as verified against the original `chan-sccp/chan-sccp` driver until the database, feature flags, provisioning and FreePBX 17 workflows have been tested together.

## Tests

```bash
bash -n install.sh
bash -n install-stack.sh
bash -n install-manager.sh
bash -n scripts/tomos-sccp-doctor.sh
bash -n scripts/tomos-sccp-install-tftp-templates.sh
bash tests/test-installer-static.sh
bash tests/test-tftp-templates.sh
python3 tests/test-modules-conf.py
python3 tests/test-sccp-provision.py
python3 tests/test-sccp-tftp.py
```

GitHub Actions runs ShellCheck, syntax checks, static checks, module-configuration idempotence tests and safe TFTP template deployment and SCCP provisioning and Cisco TFTP XML generation tests.

## Upstream and licensing

The SCCP channel driver and its configuration/template assets are maintained by the [chan-sccp project](https://github.com/chan-sccp/chan-sccp). TomOS downloads and builds that upstream source at install time; it does not claim authorship of the driver or relicense upstream files. See the upstream `COPYING` and `LICENSE` files for the driver's terms.

TomOS-specific installer and helper scripts are MIT-licensed; see [LICENSE](LICENSE). Third-party components retain their own licences.
