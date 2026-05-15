# Contributing

Contributions are welcome, especially compatibility reports for additional QNAP QuRouter models and firmware versions.

## Useful Contributions

- Test results on other QNAP QuRouter models.
- Test results on newer or older QuRouter firmware versions.
- Fixes for changed API paths or response schemas.
- Improvements to Zabbix preprocessing, discovery rules, triggers, or documentation.
- Safer troubleshooting notes for common import/runtime errors.

## Before Opening A Pull Request

- Do not include credentials, tokens, cookies, MAC addresses, serial numbers, public IPs, private IPs, hostnames, screenshots with identifiable data, or raw router JSON responses.
- Do not include files generated under `raw/` or `artifacts/`.
- Do not include QNAP frontend JavaScript bundles or other proprietary router assets.
- Import the template into Zabbix 7.0 and confirm there are no import errors.
- Confirm the master item collects data and dependent items populate correctly.
- Confirm discovery rules create expected WAN, Ethernet, switch, and Wi-Fi entities.

## Compatibility Report Template

When reporting success or a problem on a device, include only sanitized information:

```text
Router model: QNAP <model>
QuRouter firmware: <version>
Zabbix version: <version>
Zabbix component: server or proxy
Import result: success or error
Collection result: success, partial, or failed
Discovery result: WAN/Ethernet/Wi-Fi discovered correctly or not
Notes: sanitized description
```

## Development Notes

- Keep the template compatible with Zabbix 7.0 unless a version bump is intentional.
- Prefer dependent items over additional direct API calls.
- Keep the master JSON item without history to avoid storing raw API payloads.
- Use contextual macros for triggers that should only apply to selected interfaces.
- Avoid destructive or configuration-changing API calls; monitoring should use `GET` only after login.

## Security Hygiene

Before publishing logs, reports, or generated files, remove:

- Local usernames
- Passwords and token-like values
- MAC addresses and serial numbers
- Public and private IP addresses
- Hostnames and device names
- Client lists and event logs
- Router configuration fragments
