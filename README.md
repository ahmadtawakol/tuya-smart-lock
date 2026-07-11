# Tuya Smart Lock

[![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=flat-square)](https://hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/ahmadtawakol/tuya-smart-lock?style=flat-square)](https://github.com/ahmadtawakol/tuya-smart-lock/releases)
[![License](https://img.shields.io/github/license/ahmadtawakol/tuya-smart-lock?style=flat-square)](LICENSE)

A Home Assistant custom integration for controlling and observing supported Tuya
smart locks through the Tuya Cloud API. This fork adds `videolock` control,
physical-state confirmation, battery and duress telemetry, and lock events.

## Background and supported target

This project is a fork of
[nicolasglg/tuya-smart-lock](https://github.com/nicolasglg/tuya-smart-lock).
The original integration and this fork are distributed under the MIT License;
see [LICENSE](LICENSE).

Home Assistant's official Tuya integration relies on Tuya device handlers and
the device-sharing SDK. The `videolock` handler does not expose a controllable
Home Assistant `lock` platform, and a custom integration cannot add a lock
platform to that official device handler. This integration instead uses Tuya's
Smart Lock Open Service and its ticket-based cloud command flow.

The release target is the `videolock` product model `mredcfxelhrjearc`. Other
Tuya lock categories remain discoverable, but hardware not listed here has not
been live-verified for this release.

## Entities and semantics

| Entity | Home Assistant platform | Source and behavior |
| --- | --- | --- |
| Lock | `lock` | `lock_motor_state`: exact boolean `false` is locked and exact boolean `true` is unlocked. Missing or non-boolean data is unknown. Lock/unlock commands wait for bounded physical-state confirmation. |
| Battery | `sensor` | Percentage from `battery_percentage`, falling back to `residual_electricity`; only finite numeric values are accepted. |
| Duress | `binary_sensor` | Safety state from `hijack`; only exact booleans are accepted. |
| Doorbell | `event` | Emits the `ring` event type from `doorbell`. |
| Opened inside | `event` | Emits `opened` from `open_inside`. |
| Lock alarm | `event` | Emits `alarm` from `alarm_lock`; a non-empty string may appear as `reason`. |
| Unlocked | `event` | One entity for password, fingerprint, card, face, palm, temporary-code, physical-key, phone-remote, and dynamic-code unlock methods. |

The unlocked event exposes `credential_id` only when Tuya returns an exact
integer. Treat that identifier as private household telemetry: it can appear in
Home Assistant event attributes, but the integration does not write it to logs.

## Prerequisites

1. Create a **Smart Home** cloud project at
   [Tuya IoT Platform](https://iot.tuya.com).
2. Select the data center that owns the app account and devices. Choose the
   integration region that matches it: Europe, Americas, China, or India. The
   target-device diagnostic used the US data center and **Americas** region.
3. Under **Devices > Link Tuya App Account**, link the Tuya Smart or Smart Life
   account that owns the lock and confirm that the device appears in the cloud
   project.
4. Under **Service API**, authorize both **IoT Core** and
   **Smart Lock Open Service**. Renew either service if its trial has expired.
5. In the lock's Tuya Smart or Smart Life settings, enable remote locking and
   remote unlock/password-free remote control. Availability and wording depend
   on the lock firmware and app.
6. Copy the cloud project's **Access ID** and **Access Secret** for setup.

Remote door control is safety-sensitive. Confirm that the mobile app can lock
and unlock the device before configuring Home Assistant.

## Installation

### Manual

1. Download or clone this repository.
2. Copy the complete `custom_components/tuya_smart_lock` directory into the
   Home Assistant configuration directory as
   `custom_components/tuya_smart_lock`.
3. Restart Home Assistant.
4. Add the integration from **Settings > Devices & services > Add integration >
   Tuya Smart Lock**.

### HACS custom repository

1. In HACS, open **Integrations**, then **Custom repositories**.
2. Add `https://github.com/ahmadtawakol/tuya-smart-lock` with category
   **Integration**.
3. Install **Tuya Smart Lock**, restart Home Assistant, and add the integration
   from **Settings > Devices & services**.

HACS installs releases, not an unpublished branch. A `v1.1.0` GitHub release and
tag must exist before HACS users can receive the code described here. Until
then, use the manual installation method; this README does not claim that
`v1.1.0` is already published.

## Configuration

Configuration is UI-only; no YAML is required.

1. Enter the Tuya cloud project's **Access ID**, **Access Secret**, and matching
   **API Region**.
2. Select a discovered lock.
3. The setup flow verifies password-free remote unlock before saving the config
   entry. Repeat the flow for additional locks.

The credentials are stored in the Home Assistant config entry. Protect Home
Assistant backups and configuration storage accordingly. Access secrets, access
tokens, command tickets, raw Tuya response payloads, and raw credential payloads
are not logged by this integration.

## Runtime behavior and limitations

- This integration is cloud-only; physical lock functions remain available
  when the internet or Tuya Cloud is unavailable.
- A shared coordinator polls Tuya's latest shadow properties every 30 seconds.
  The shadow endpoint exposes the latest property, not a durable event stream,
  so multiple identical events inside one polling window can collapse into one
  observed event.
- Every Tuya HTTP request has a 12-second timeout.
- Commands use the Tuya password-ticket flow. After Tuya accepts a command, the
  integration refreshes after bounded delays of 2, 3, and 5 seconds and reports
  success only when the physical motor state is confirmed.
- Camera streams, on-screen display (OSD), password/credential management, and
  other video-lock administration are outside this integration's scope.

For cautious on-device validation, use the
[live verification checklist](docs/live-verification.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Invalid authentication | Re-copy the Access ID and Access Secret from the intended Smart Home project. Do not use app login credentials. |
| Service expired or not authorized | Authorize or renew both IoT Core and Smart Lock Open Service in the same cloud project. |
| Rate limited | Wait at least a minute before retrying and avoid repeatedly reloading or sending commands. |
| No devices, unavailable entity, or connection failure | Verify the linked app account, matching data center/API region, internet access, and Tuya Cloud status. A US-hosted project must use **Americas**. |
| Remote control disabled | Enable both remote lock and password-free remote unlock in the mobile app, then run setup again. |
| Device unavailable | Confirm it is online in the Tuya Smart or Smart Life app. The integration marks entities unavailable when cloud refreshes fail and restores them after recovery. |
| Command accepted but not confirmed | Observe the door safely and check device connectivity. Tuya accepted the request, but the expected motor state did not appear during the bounded confirmation window; do not assume the door changed state. |

When reporting a problem, include Home Assistant and integration versions,
device category/model, API region, and sanitized diagnostics. Never include an
Access Secret, access token, command ticket, device/account identifier, or raw
credential payload. File issues at
[ahmadtawakol/tuya-smart-lock](https://github.com/ahmadtawakol/tuya-smart-lock/issues).

## License

MIT License. See [LICENSE](LICENSE).
