# TomOS SCCP for FreePBX 17

TomOS SCCP is an installer and operations helper for the FreePBX 17-tested [chan-sccp driver fork](https://github.com/nortien/chan-sccp) Asterisk channel driver on FreePBX 17 / Debian 12. It does not reimplement or fork the SCCP protocol driver.

> **Status:** early integration release. CI/static tests are not a substitute for testing against a real FreePBX 17 installation and physical Cisco handsets. Back up the PBX and test on a staging system before production use.

## Features

- Builds upstream chan-sccp against the Asterisk development headers already installed.
- Detects the active Asterisk module directory.
- Stages the build before replacing the active module.
- Backs up the existing SCCP module and modules.conf.
- Adds a marked, repeatable modules.conf block to load chan_sccp and prevent chan_skinny conflicts.
- Checks documented Asterisk module dependencies.
- Records the upstream source commit used for the build.
- Installs a read-only diagnostic utility.
- Provides a full-stack installer for the driver and the upstream FreePBX SCCP Manager GUI companion.
- Supports selecting an upstream Git ref with TOMOS_SCCP_REF (default: stable).

## One-line installation

Review the installer before running it. On a supported FreePBX 17 host:

```bash
curl -fsSL https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main/install-stack.sh | sudo bash
```

To install only the channel driver (without the FreePBX GUI companion):

```bash
curl -fsSL https://raw.githubusercontent.com/Spruhantom/Tomos-sccp/main/install.sh | sudo bash
```

The driver-only installer accepts `TOMOS_SCCP_REF` to select a different upstream ref.

The installer requires root, installs build dependencies through APT, and downloads upstream source from GitHub. It does not install an unverified prebuilt binary.

## Compatibility and requirements

- FreePBX 17 on Debian 12.
- A running Asterisk 18–23 instance.
- Development headers matching the exact Asterisk build, including /usr/include/asterisk.h and /usr/include/asterisk/module.h.
- Network access to Debian package repositories and GitHub.
- The Asterisk service account named asterisk.
- A verified PBX backup.

**Header compatibility is critical.** The installer deliberately refuses to substitute generic Debian Asterisk headers for missing vendor-matched headers. Install the matching FreePBX/Sangoma development package before retrying.

The upstream driver documents these dependencies: app_voicemail, bridge_simple, bridge_native_rtp, bridge_softmix, bridge_holding, res_stasis and res_stasis_device_state. The installer checks these before replacing the active driver.

## Diagnostics

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-doctor.sh
```

Manual checks:

```bash
sudo asterisk -rx 'module show like chan_sccp.so'
sudo asterisk -rx 'sccp show devices'
sudo asterisk -rx 'sccp show lines'
sudo journalctl -u asterisk -n 100
```

## FreePBX module loading

The installer manages only its marked block in /etc/asterisk/modules.conf. FreePBX may regenerate this file. After applying FreePBX configuration, verify in **Admin → Asterisk Modules** that chan_sccp.so is manually loaded and chan_skinny.so is excluded. Avoid duplicate directives.

## Phone provisioning

The full-stack installer also installs the upstream GPL-licensed [SCCP Manager](https://github.com/nortien/sccp_manager) companion into FreePBX. It provides GUI management for devices, lines, buttons, phone models and TFTP provisioning. TomOS does not fork or relicense that module. The driver-only installer does not install the GUI companion.

The installer does not invent phone credentials or automatically expose devices to the network. Review the manager's security settings, device allow-lists, TFTP root and DHCP option 150 before connecting phones. Read the [upstream installation and provisioning guide](https://github.com/nortien/sccp_manager/wiki).

## Tests

```bash
bash -n install.sh
bash -n scripts/tomos-sccp-doctor.sh
bash -n install-manager.sh
bash -n install-stack.sh
bash tests/test-installer-static.sh
python3 tests/test-modules-conf.py
```

GitHub Actions runs ShellCheck, Bash syntax checks and the static/idempotence tests.

## Upstream and licence

The SCCP protocol implementation originates with [chan-sccp](https://github.com/chan-sccp/chan-sccp); TomOS builds the FreePBX 17-tested [nortien driver fork](https://github.com/nortien/chan-sccp). The companion [SCCP Manager](https://github.com/nortien/sccp_manager) provides FreePBX GUI device, line, button and TFTP provisioning; its separate GPL licence and installation are documented upstream. TomOS provides integration and operational tooling and does not claim ownership of the upstream driver. The TomOS scripts are MIT-licensed; see [LICENSE](LICENSE). The upstream driver retains its own licence.
