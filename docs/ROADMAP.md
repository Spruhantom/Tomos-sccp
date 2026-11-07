# Development roadmap

TomOS SCCP is an integration layer around the original [chan-sccp/chan-sccp](https://github.com/chan-sccp/chan-sccp) driver. The upstream project remains responsible for the SCCP protocol implementation; TomOS owns FreePBX integration, safe installation, provisioning workflows, diagnostics and tests.

## Milestone 1 — upstream driver integration
- [x] Use the original chan-sccp Git repository as the build source
- [x] Detect FreePBX 17 / Debian 12 and the running Asterisk module directory
- [x] Build with upstream configure/build/install targets
- [x] Enable upstream conference support without experimental flags
- [x] Stage the build before replacing the active module
- [x] Back up the existing driver and module configuration
- [x] Manage an idempotent TomOS-owned modules.conf block
- [x] Check required Asterisk module dependencies
- [x] Record the exact upstream source commit
- [ ] Test on clean FreePBX 17 images with Asterisk 20, 22 and 23
- [ ] Verify upgrade and rollback with active calls drained

## Milestone 2 — Cisco provisioning assets
- [x] Stage upstream SCCP config examples separately from live PBX configuration
- [x] Stage upstream Cisco phone model/TFTP templates
- [x] Add an explicit TFTP-root deployment helper
- [x] Preserve existing TFTP files and never deploy sample credentials automatically
- [ ] Validate supported phone models and firmware against target handsets
- [ ] Verify DHCP option 150, TFTP and generated SEP<MAC>.cnf.xml
- [ ] Test registration and inbound/outbound calls with physical Cisco phones

## Milestone 3 — FreePBX administration
- [x] Identify the existing SCCP Manager companion project
- [x] Keep GUI manager installation opt-in pending driver compatibility tests
- [ ] Verify manager database/realtime requirements against the original upstream driver
- [ ] Confirm feature flags required for manager compatibility
- [ ] Integrate device and line administration with FreePBX 17 permissions
- [ ] Test module install, upgrade, backup and uninstall on clean FreePBX 17

## Milestone 4 — TomOS management and monitoring
- [ ] TomOS-branded FreePBX administration workflow
- [x] JSON-based device inventory and MAC-address validation (staging renderer)
- [ ] Network device discovery
- [x] Generate SCCP device/line include fragments without touching live configuration
- [ ] FreePBX extension creation and line provisioning with secret-safe configuration
- [ ] Registration/session status dashboard
- [ ] BLF and presence monitoring
- [ ] Firmware inventory and model compatibility reporting
- [ ] Structured logs and support bundle generation
- [ ] Upgrade health checks and recovery workflow

## Release gates

A release must not be described as production-ready until CI passes, install/upgrade/uninstall has been tested on supported FreePBX 17 images, and phone registration, inbound/outbound calling, transfer, hold, voicemail indication, BLF and reboot persistence have been validated with real Cisco handsets.

## Scope and upstream

TomOS does not fork or replace the upstream SCCP protocol driver. Driver fixes should be contributed upstream where practical; TomOS-specific code should remain isolated in its installer, FreePBX integration, provisioning and operations tooling.
