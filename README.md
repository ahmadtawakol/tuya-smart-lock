# Tuya Smart Lock

[![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=flat-square)](https://hacs.xyz/)
[![GitHub Release](https://img.shields.io/github/v/release/ahmadtawakol/tuya-smart-lock?style=flat-square)](https://github.com/ahmadtawakol/tuya-smart-lock/releases)
[![License](https://img.shields.io/github/license/ahmadtawakol/tuya-smart-lock?style=flat-square)](LICENSE)

A Home Assistant custom integration for observing and experimentally controlling
supported Tuya smart locks through the free app-authenticated session provided by
Home Assistant's official Tuya integration. It adds a `videolock` lock entity,
physical-state confirmation, battery and duress telemetry, and lock events.

## Background and supported target

This project is a fork of
[nicolasglg/tuya-smart-lock](https://github.com/nicolasglg/tuya-smart-lock).
The original integration and this fork are distributed under the MIT License;
see [LICENSE](LICENSE).

Home Assistant's official Tuya integration relies on Tuya's Device Sharing SDK,
but deliberately does not expose a Home Assistant `lock` platform. This
integration reuses that already authenticated SDK session and adds its own lock
and telemetry entities. No Tuya developer subscription is required for new
setups: there is no developer project, Access ID, Access Secret, IoT Core, or
Smart Lock Open Service configuration.

Control in `v1.2.0-beta.1` is experimental. The target lock advertises
`lock_motor_state` as a writable Device Sharing function, so the integration
sends that standard datapoint and reports success only after the physical state
changes. Tuya may reject or ignore the command on some locks because its
documented remote-unlock flow normally uses a privileged security ticket. State
and telemetry can still work when control is unavailable.

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

1. Run **Home Assistant 2026.7.2 or newer**. Older Home Assistant releases and
   older Python runtimes are unsupported; this integration targets Python 3.14
   or newer.
2. Add the lock to the **Tuya Smart** or **Smart Life** mobile app.
3. Set up Home Assistant's built-in **Tuya** integration using its User Code and
   QR-code app login. Confirm the lock appears there, even if it is marked
   unsupported or has no entities.
4. In the lock's Tuya Smart or Smart Life settings, enable remote locking and
   remote unlock/password-free remote control. Availability and wording depend
   on the lock firmware and app.

Remote door control is safety-sensitive. Confirm that the mobile app can lock
and unlock the device before configuring Home Assistant. Keep an authorized
person at the door and preserve a physical entry method during beta testing.

## Installation

### HACS custom repository (recommended)

[![Open your Home Assistant instance and add this repository to HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ahmadtawakol&repository=tuya-smart-lock&category=integration)

This repository is installed as a HACS custom repository; it is not listed in
the HACS default catalog.

1. Verify that you are running Home Assistant 2026.7.2 or newer.
2. Choose one path to open the repository:
   - **Badge:** Select the button above. It opens the Tuya Smart Lock repository
     directly in HACS. Skip the custom-repository URL, type, and **Add** dialog
     and continue with **Download** below.
   - **Manual:** Open HACS, select the upper-right three-dot menu, then select
     **Custom repositories**. Enter
     `https://github.com/ahmadtawakol/tuya-smart-lock`, choose **Integration**,
     select **Add**, then open **Tuya Smart Lock** in HACS.

After either path, on the Tuya Smart Lock repository page:

1. Select **Download**.
2. Restart Home Assistant.
3. Go to **Settings > Devices & services > Add integration > Tuya Smart Lock**.

Future published releases appear as updates in HACS. Install an update from
**Settings > Updates** by selecting **Install**. Alternatively, in HACS find
Tuya Smart Lock with the **Pending update** status, open its three-dot menu, and
select **Redownload**. After using either path, restart Home Assistant afterward.

### Manual installation (fallback)

1. Download or clone this repository.
2. Copy the complete `custom_components/tuya_smart_lock` directory into the
   Home Assistant configuration directory as
   `custom_components/tuya_smart_lock`.
3. Restart Home Assistant.
4. Add the integration from **Settings > Devices & services > Add integration >
   Tuya Smart Lock**.

## Configuration

Configuration is UI-only; no YAML is required.

1. Configure Home Assistant's official **Tuya** integration with the Tuya or
   Smart Life app.
2. Add **Tuya Smart Lock** and select a discovered lock.
3. Repeat the custom integration flow for additional locks.

New entries store only the official Tuya config-entry ID, device ID, and device
name. Authentication tokens stay owned by Home Assistant's official Tuya
integration and are never copied into this custom integration.

Existing `v1.1.0` cloud-credential entries continue to work while their Tuya
developer subscription remains active. To switch one without changing entity
identities, open its integration menu, select **Reconfigure**, and confirm the
matching lock from the official Tuya session. The old Access ID, Access Secret,
and API region are then removed from that config entry.

## Runtime behavior and limitations

- This integration remains cloud-dependent; physical lock functions remain
  available when the internet or Tuya Cloud is unavailable.
- State comes from the official Tuya integration's Device Sharing cache. MQTT
  updates are forwarded immediately with datapoint timestamps, with a 30-second
  cached-state refresh as a fallback.
- Commands send the standard `lock_motor_state` datapoint through Device
  Sharing. After sending, the integration checks after bounded delays of 2, 3,
  and 5 seconds and reports success only when the physical motor state is
  confirmed. A timeout means control is unsupported or the lock did not move;
  never assume the door changed state.
- Legacy `v1.1.0` entries retain the paid ticket-based OpenAPI path until they
  are reconfigured.
- Camera streams, on-screen display (OSD), password/credential management, and
  other video-lock administration are outside this integration's scope.

For cautious on-device validation, use the
[live verification checklist](docs/live-verification.md).

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Official Tuya integration required | Add Home Assistant's built-in Tuya integration first and complete its QR-code login with the Tuya or Smart Life app. |
| No lock listed | Reload the official Tuya integration and confirm the lock appears in its device list. The lock can be marked unsupported there and still be selectable here. |
| Standard command rejected or not confirmed | The free Device Sharing session may provide telemetry but not privileged remote lock control. Observe the door safely; do not assume it moved. |
| Legacy authentication or expired service | Reconfigure the existing Tuya Smart Lock entry to the official Tuya session. Paid IoT Core and Smart Lock Open Service are needed only if retaining legacy mode. |
| Rate limited | Wait at least a minute before retrying and avoid repeatedly reloading or sending commands. |
| Unavailable entity or connection failure | Verify the official Tuya integration, internet access, and Tuya Cloud status. Reload official Tuya before reloading this integration. |
| Remote control disabled | Enable both remote lock and password-free remote unlock in the mobile app, then run setup again. |
| Device unavailable | Confirm it is online in the Tuya Smart or Smart Life app. The integration marks entities unavailable when cloud refreshes fail and restores them after recovery. |
| Command accepted but not confirmed | Observe the door safely and check device connectivity. Tuya accepted the request, but the expected motor state did not appear during the bounded confirmation window; do not assume the door changed state. |

When reporting a problem, include Home Assistant and integration versions,
device category/model, whether the action was lock or unlock, and sanitized
diagnostics. Never include an Access Secret, app token, QR code, device/account
identifier, credential ID, or raw credential payload.

## Support status

[GitHub Issues on the fork](https://github.com/ahmadtawakol/tuya-smart-lock/issues)
is the active support path for sanitized bug reports and support requests.

## License

MIT License. See [LICENSE](LICENSE).
