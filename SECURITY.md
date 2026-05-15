# Security Policy

This project documents and monitors undocumented QuRouter API endpoints. Treat every collected payload as potentially sensitive.

## Sensitive Data

Do not publish:

- Router credentials
- Bearer tokens, cookies, session IDs, or API keys
- Router serial numbers or base MAC addresses
- WAN public IP addresses
- LAN/private IP addressing plans
- Client MAC addresses, hostnames, or DHCP data
- Event logs or VPN logs
- Raw API responses from your router
- Downloaded QuRouter frontend bundles from `raw/`

## Safe To Publish

Usually safe:

- Sanitized documentation
- The Zabbix template YAML
- Sanitized scripts that use placeholders like `https://<ROUTER_IP>`
- Endpoint paths without real response payloads
- Model and firmware version, if you are comfortable sharing them

## Reporting Security Issues

If you find a security issue in this repository, open a GitHub issue with a sanitized description. Do not include exploit details, real credentials, tokens, public IPs, serial numbers, MAC addresses, or raw router responses.

If the issue is a vulnerability in QNAP QuRouter itself, report it to QNAP through their official security channel.

## Operational Notes

- The template performs a login request and then uses authenticated `GET` requests.
- The default `force_login` behavior may close an existing QuRouter web session.
- The template does not intentionally perform `PUT`, `DELETE`, or configuration-changing API calls.
- The APIs are not officially documented by QNAP and may change without notice.
