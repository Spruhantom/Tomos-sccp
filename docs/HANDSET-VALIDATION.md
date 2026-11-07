# Cisco handset validation runbook

This procedure separates software checks from proof on a physical phone. Record the exact phone model, hardware revision, firmware load, PBX/Asterisk version, and test date for every handset tested.

## 1. Prepare a safe test environment

- Use a staging FreePBX/Asterisk host and a dedicated voice VLAN or isolated test network.
- Back up FreePBX, Asterisk and DHCP/TFTP configuration.
- Create a test extension and a unique device entry for the phone's printed MAC address.
- Confirm the selected upstream SEP template family matches the actual model; template family names are not a firmware compatibility promise.
- Confirm the phone can reach the PBX and TFTP server, including required UDP/TFTP and SCCP TCP traffic through any firewall.

## 2. Verify TFTP before connecting the phone

1. Generate and review the SEP export and its manifest.
2. Deploy only after approving the exact manifest digest.
3. Run the live read-back checker from a host that can reach the TFTP service:

   ```bash
   sudo /usr/local/libexec/tomos-sccp/tomos-sccp-tftp-check.py \
     --server 192.168.10.5 \
     --staging-dir /var/tmp/tomos-sccp-tftp-review
   ```

4. Confirm DHCP Option 150 points to the intended TFTP server. Check that the server also provides the correct call-manager XML and that required model firmware is already installed or available from a trusted source.

A successful read-back proves only that TFTP served bytes matching the reviewed files. It does not prove that the phone requests those filenames or accepts the XML.

## 3. Connect one handset and inspect Asterisk

Connect one test phone, observe its boot process and collect the PBX snapshot:

```bash
sudo /usr/local/libexec/tomos-sccp/tomos-sccp-phone-check.sh \
  --mac 001122AABBCC --extension 1000
```

Review the output of `sccp show devices`, `sccp show lines` and the Asterisk service log. Confirm the exact MAC is present, the intended line/extension is associated, and the device is registered/online according to the driver output. Do not treat the presence of a configured device as proof of registration.

If it does not register, preserve the phone display/error, DHCP lease, TFTP server logs, packet capture where permitted, and Asterisk logs. Check MAC, model/template family, XML contents, firmware, PBX address/port, SCCP configuration, network reachability and clock/NTP settings. Avoid posting credentials, phone configuration secrets or public IPs in issue reports.

## 4. Call and media test

Using a second known-good endpoint, record each result separately:

- Phone boots and obtains the expected address, gateway, DNS and Option 150.
- Phone retrieves the expected XMLDefault and SEP XML files.
- Phone registers and remains registered for at least 15 minutes.
- Outbound call to the test endpoint connects.
- Inbound call to the phone's extension rings and connects.
- Two-way audio is present in both directions for at least 60 seconds.
- Hold/resume, transfer and conference are tested only if those features are in scope.
- Repeat with the phone behind the intended VLAN/firewall/NAT topology.

A call that connects without two-way audio is a failed media test. Record codec negotiation, RTP ports and firewall/NAT observations when diagnosing audio.

## 5. Compatibility evidence matrix

Create one row per physical model and firmware combination. Do not generalise a pass to other models or firmware loads.

| Model | Hardware revision | Firmware | SEP template family | TFTP | Registered | Outbound | Inbound | Two-way audio | Notes |
|---|---|---|---|---|---|---|---|---|---|
| Not yet tested | — | — | — | Not tested | Not tested | Not tested | Not tested | Not tested | Awaiting hardware |

## Acceptance criteria

A model/firmware combination is validated only when the exact phone retrieves the intended configuration, registers to the test PBX, completes inbound and outbound calls, and passes two-way audio. Keep the project in development status until this evidence exists for the target fleet.
