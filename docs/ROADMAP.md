# Development roadmap

This repository currently provides the SCCP driver build/install integration and diagnostics. The roadmap deliberately separates the channel driver from FreePBX administration and phone provisioning.

## Milestone 1 — installer foundation
- [x] Debian 12 / FreePBX 17 platform guard
- [x] Detect running Asterisk major version and module directory
- [x] Require vendor-matched Asterisk headers
- [x] Build upstream driver and stage the install
- [x] Back up existing module and module configuration
- [x] Manage an idempotent TomOS-owned modules.conf block
- [x] Read-only diagnostic utility
- [x] Static and configuration idempotence tests
- [ ] Test on clean FreePBX 17 images with Asterisk 20, 22 and 23
- [ ] Verify upgrade and rollback with live calls drained

## Milestone 2 — Cisco phone provisioning
- [ ] Define supported device models and firmware matrix
- [ ] Create safe device/line configuration schema
- [ ] Validate MAC addresses, extension references and secrets
- [ ] Generate SEP<MAC>.cnf.xml using upstream-supported templates
- [ ] Configure TFTP service without replacing an existing TFTP setup
- [ ] Provide provisioning preview, validation and rollback
- [ ] Test registration and calls with physical Cisco handsets

## Milestone 3 — FreePBX integration
- [x] Identify the FreePBX 17-tested SCCP Manager companion (nortien/sccp_manager 17.1.1)
- [ ] Validate its GPL module and driver compatibility against TomOS build output
- [ ] Decide whether TomOS ships a branded fork or installs the upstream companion unchanged
- [ ] Integrate GUI installation/upgrade without overwriting existing FreePBX settings
- [ ] Test module install, upgrade and uninstall on clean FreePBX 17 images

## Milestone 4 — operations and monitoring
- [ ] Registration/session status
- [ ] Line, BLF and presence visibility
- [ ] Firmware inventory and model compatibility reporting
- [ ] Structured logs and support bundle generation
- [ ] Upgrade health checks and recovery workflow

## Release gates

A release must not be described as production-ready until CI passes, install/upgrade/uninstall has been tested on supported FreePBX 17 images, and registration, inbound/outbound calling, transfer, hold, voicemail indication and reboot persistence have been validated with real Cisco phones.

## Scope and upstream

The SCCP protocol driver remains the upstream [chan-sccp project](https://github.com/chan-sccp/chan-sccp). This repository owns TomOS-specific packaging, FreePBX integration, provisioning orchestration, tests and documentation.
