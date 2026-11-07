# Cisco SCCP model and firmware compatibility

## Scope and evidence status

The first hardware-validation targets are the Cisco 7940, 7960 and 7970. These are **provisioning candidates**, not certified working combinations. TomOS uses the original upstream chan-sccp driver and upstream SEP XML templates; it does not provide Cisco firmware images or infer firmware compatibility from a template filename.

No physical handset is currently available for this project. Consequently, firmware requirements, TFTP acceptance, registration, button behaviour, call setup and audio are all **not yet verified**. Do not treat a passing CI job or successful XML render as a compatibility certification.

## Initial target matrix

| Cisco model | SCCP device type | SEP template family | Firmware requirement | Current status |
|---|---:|---|---|---|
| 7940 | 7940 | `7940_7960` | Exact supported SCCP load not yet established; record the phone's installed load and verify against Cisco/chan-sccp documentation before deployment | Candidate; no hardware test |
| 7960 | 7960 | `7940_7960` | Exact supported SCCP load not yet established; record the phone's installed load and verify against Cisco/chan-sccp documentation before deployment | Candidate; no hardware test |
| 7970 | 7970 | `797x` | Exact supported SCCP load not yet established; record the phone's installed load and verify against Cisco/chan-sccp documentation before deployment | Candidate; no hardware test |

The manager enforces these three model-to-template-family pairings. Other Cisco models remain in the broader upstream template catalogue, but are outside this initial target milestone and must not be described as hardware-supported.

## Provisioning validation

For each target model:

1. Confirm the printed model and MAC address on the handset.
2. Record the complete firmware/load identifier from the phone's status menu.
3. Select the matching template family from the table above.
4. Render `SEP<MAC>.cnf.xml` using the manager's staging export.
5. Parse the XML and check the PBX address, SCCP port, MAC-derived filename, absence of unresolved address placeholders and absence of upstream sample SSH credentials.
6. Review all model-specific XML options against the exact firmware release before approving deployment.
7. Deploy only the reviewed manifest into an existing TFTP root; verify the served bytes with the TFTP read-back checker.
8. Capture DHCP Option 150 and TFTP request logs when the handset boots.

CI exercises the manager's model/family selection and XML renderer with synthetic fixture templates. This validates TomOS transformations and rejection rules; it does not validate the real upstream template contents for every released firmware.

## Asterisk / chan-sccp staging integration

Run the following on an isolated staging PBX built with the same Asterisk version and chan-sccp source revision intended for deployment:

```bash
asterisk -rx 'core show version'
asterisk -rx 'module show like chan_sccp.so'
asterisk -rx 'sccp show devices'
asterisk -rx 'sccp show lines'
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-phone-check.sh --mac 001122AABBCC --extension 1000
```

Record the Asterisk version, chan-sccp commit/build, configuration revision, device state and line state. Asterisk CLI output from an actual daemon with chan-sccp loaded is required for the staging integration result. The repository's mocked CLI tests only test the diagnostic and inventory code paths; they do not prove the channel driver is running.

Registration requires an actual SCCP endpoint. Do not mark registration passed from a static device configuration or an inventory record.

## Feature/button test cases

For each physical phone and firmware:

- Speed dial: press the configured key and confirm the intended destination is dialled.
- BLF: observe idle, ringing and busy state on a monitored extension; confirm recovery to idle.
- DND: activate/deactivate from the configured key and verify inbound call handling.
- Call forwarding: enable, test forwarding to the configured destination, then disable and retest.
- Line keys: verify the configured line is selectable and calls use the expected extension.
- Reboot persistence: reboot the handset and confirm its line and button assignments remain correct.

Record unsupported functions rather than assuming a generic feature button behaves identically across models.

## Hardware acceptance record

Use one record per physical handset. Capture the handset model, hardware revision, MAC (redact in public reports), exact firmware load, PBX version, chan-sccp commit, SEP template family and date. Mark each item Pass, Fail or Not tested:

- TFTP file retrieval and XML acceptance
- SCCP registration and 15-minute registration stability
- Correct line/extension association
- Speed dial
- BLF idle/ringing/busy indication
- DND
- Call forwarding
- Outbound call
- Inbound call
- Two-way audio in both directions for at least 60 seconds
- Reboot and registration persistence

A model/firmware combination is validated only after all required tests pass on that exact combination. Until then, retain the **not hardware-verified** status.
