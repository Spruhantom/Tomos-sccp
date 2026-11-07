# Upstream adaptation notes

## Reference project

TomOS uses the original [chan-sccp/chan-sccp](https://github.com/chan-sccp/chan-sccp) repository as its source of truth for the SCCP Asterisk channel driver.

The installer defaults to the upstream `develop` branch and records the exact Git commit used. Set `TOMOS_SCCP_REF` to a reviewed branch or tag when pinning a deployment.

## What is adapted

| Upstream component | TomOS integration |
|---|---|
| `configure`, `Makefile`, `src/` | Built from the upstream checkout; no private reimplementation |
| Asterisk module loading guidance | Managed TomOS block in `modules.conf`; prevents `chan_skinny.so` conflict |
| Required Asterisk module list | Pre-install dependency/load checks |
| `conf/sccp.conf.minimal` and FreePBX examples | Staged under `/usr/share/tomos-sccp/examples`; never overwrite live config |
| `conf/tftp/*_template` and XML defaults | Staged under `/usr/share/tomos-sccp/tftp-templates` |
| Phone template deployment | Explicit TFTP-root command; existing files are preserved |

TomOS currently passes `--enable-conference` to upstream configure. Experimental options such as advanced functions and video are not enabled by default. Distributed device state is not enabled because the upstream configure documentation limits it to old Asterisk versions.

## Safety differences from a raw upstream install

- The driver is built and installed into a temporary `DESTDIR` staging directory first.
- The previous module and `modules.conf` are backed up.
- The live module is unloaded before its file is replaced.
- TomOS does not copy upstream demo configuration into `/etc/asterisk`.
- Example files contain sample device entries and credentials; operators must review them.
- TFTP templates are copied only when the destination file does not already exist.
- TFTP daemon, DHCP, firewall and phone firmware configuration are not changed automatically.

## FreePBX GUI manager

The separate optional GUI manager installer currently references the Nortien manager fork. Its compatibility with the original upstream driver is not yet established. The full-stack installer therefore leaves GUI installation disabled unless the operator explicitly sets `TOMOS_SCCP_INSTALL_MANAGER=1`. Do not enable this on a production PBX until compatibility testing is complete.

## Licensing

The SCCP driver and upstream configuration/template assets remain under the licences provided by the upstream repository (see `COPYING` and `LICENSE`). TomOS does not copy the driver source into its MIT-licensed helper repository and does not change upstream copyright or licence notices. TomOS-specific installer and helper scripts are MIT-licensed.
