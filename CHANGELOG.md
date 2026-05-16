# Changelog

All notable changes to this project should be documented here.

## Unreleased

- Added template graphs for system, memory, clients/events, and health state metrics.
- Added LLD graph prototypes for WAN, Ethernet, switch, and Wi-Fi discovery rules.
- Added host dashboard `QuRouter overview` with overview and interface pages.

## 1.0.0 - Initial Public Release

- Added Zabbix 7.0 template for QNAP QuRouter monitoring.
- Added authenticated REST API collection using local login and Bearer token.
- Added master item with dependent items to avoid storing raw aggregate JSON history.
- Added multi-WAN monitoring and discovery.
- Added Ethernet physical port discovery with readable QHora-301W port labels.
- Added switch counter discovery for `swdev` interfaces.
- Added Wi-Fi band discovery.
- Added triggers for API health, Internet state, WAN state, CPU, memory, temperature, firmware, reboot detection, clients, and interface changes.
- Added sanitized source documentation explaining API discovery and template design.
- Added sanitized discovery/probe helper scripts.
