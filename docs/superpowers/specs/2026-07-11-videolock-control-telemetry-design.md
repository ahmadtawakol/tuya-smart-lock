# Tuya Video Lock Control and Telemetry Design

## Context

The target device is a Tuya video lock with category `videolock` and product
ID `mredcfxelhrjearc`. Home Assistant 2026.7.2 discovers the device through the
official Tuya integration but creates no entities.

The device diagnostics already contain usable status and schema data,
including `lock_motor_state`, `open_inside`, `doorbell`, `alarm_lock`, unlock
method datapoints, and battery data under `residual_electricity`. Tuya's shadow
properties API reports the same battery datapoint as `battery_percentage`.

This is not primarily a malformed-schema problem. Home Assistant does not map
the `videolock` category to its lock, sensor, binary-sensor, or event platforms,
and the official Tuya integration does not implement the Home Assistant lock
platform. A `tuya-device-handlers` quirk can patch device schemas and category
metadata before entity construction, but it cannot add the missing platform
mappings or Tuya's ticket-based smart-lock command flow. A conventional quirk
would therefore load without delivering the requested result.

The implementation will extend the existing `nicolasglg/tuya-smart-lock`
custom integration, which already implements Tuya's ticket flow and lists
`videolock` as a supported category.

## Goals

- Provide a real Home Assistant lock entity with both lock and unlock actions.
- Confirm lock state from the physical device instead of relying solely on
  optimistic state.
- Expose battery, duress, doorbell, inside-open, alarm, and unlock-method data.
- Group all new entities with the device created by the official Tuya
  integration.
- Handle both known battery datapoint names.
- Provide actionable errors for authentication, authorization, subscription,
  rate-limit, device, and command failures.
- Keep credentials, tokens, tickets, and sensitive raw lock payloads out of
  logs and entity attributes.
- Remain installable manually and compatible with HACS custom-repository
  installation.

## Non-goals

- Local control. The diagnostic reports `support_local: false`, and command
  execution uses Tuya Cloud.
- Parsing undocumented raw credential, synchronization, temporary-password,
  or lock-record payloads.
- Exposing camera, OSD, dormant-mode, capture-mode, or credential-management
  controls in the first release.
- Guaranteed lossless real-time delivery of rapid events. The first release
  polls the shadow API and can observe only the latest property value and
  timestamp.
- Publishing or opening an upstream pull request as part of the initial local
  delivery.

## Architecture

### API client

The Tuya API client owns one Home Assistant-managed HTTP session, signed Tuya
requests, and token refresh. It provides focused methods for:

- validating credentials and required service access;
- discovering supported lock devices;
- obtaining a smart-lock authorization ticket;
- operating the door with `open: true` or `open: false`;
- reading shadow properties with values and timestamps; and
- checking whether remote unlocking is enabled.

The client returns typed or normalized data to the rest of the integration and
raises domain-specific exceptions. It never exposes ticket keys or raw secrets
to entities.

### Data coordinator

A Home Assistant `DataUpdateCoordinator` performs one shared request every 30
seconds to:

`GET /v2.0/cloud/thing/{device_id}/shadow/properties`

The expected response is `result.properties`, where every property can contain
`code`, `dp_id`, `value`, and `time`. Tuya normally returns `time` as a
13-digit Unix timestamp in milliseconds. The normalizer also accepts a
10-digit Unix timestamp in seconds and converts it to milliseconds. Continuous
state values remain usable when `time` is missing or malformed, but an
event-source property without a valid timestamp cannot emit an event or advance
its event cursor. That condition is logged at debug level without including the
property value.

The coordinator normalizes valid properties into a mapping keyed by datapoint
code while retaining each property's `dp_id`, value, and normalized timestamp.

The coordinator is the only polling source for all entities. This prevents
duplicate requests and keeps availability and refresh behavior consistent.
After lock or unlock commands, the integration requests follow-up refreshes to
confirm the physical state.

### Entity platforms

The integration provides `lock`, `sensor`, `binary_sensor`, and `event`
platform modules. All entities use the same coordinator and device descriptor.
Their device identifiers remain `("tuya", device_id)`, linking them to the
official Tuya device instead of creating a duplicate device.

### Config flow

The UI config flow collects the Tuya Access ID, Access Secret, and API region,
then discovers compatible lock devices and lets the user select one. Setup
validates authentication and reports missing or expired IoT Core and Smart Lock
Open Service authorization distinctly where the Tuya response permits it.

The prerequisite documentation explains how to create a Tuya Smart Home cloud
project, link the Tuya or Smart Life account, authorize IoT Core and Smart Lock
Open Service, enable remote control, and select the matching data center.

## Entity Model

| Entity | Source datapoint(s) | Semantics |
| --- | --- | --- |
| Lock | `lock_motor_state` | `true` is unlocked and `false` is locked; supports lock and unlock commands. |
| Battery | `battery_percentage`, falling back to `residual_electricity` | Percentage sensor using whichever alias the endpoint returns. |
| Doorbell | `doorbell` | Emits event type `pressed` when the Tuya property timestamp advances. |
| Opened from inside | `open_inside` | Emits event type `opened` rather than presenting a persistent door-contact state. |
| Lock alarm | `alarm_lock` | Emits stable event type `alarm` with the reported string in the `reason` attribute. Unknown reasons remain valid. |
| Duress/hijack | `hijack` | Safety binary sensor. |
| Unlocked | Supported integer `unlock_*` datapoints | One event entity with a fixed method-specific event type and the reported numeric identifier in `credential_id`. |

The unlocked event mapping is fixed:

| Datapoint | Event type |
| --- | --- |
| `unlock_password` | `password` |
| `unlock_fingerprint` | `fingerprint` |
| `unlock_card` | `card` |
| `unlock_face` | `face` |
| `unlock_hand` | `palm` |
| `unlock_temporary` | `temporary_code` |
| `unlock_key` | `physical_key` |
| `unlock_phone_remote` | `phone_remote` |
| `unlock_dynamic` | `dynamic_code` |

`credential_id` is permitted normalized telemetry: it contains only the
integer reported by the corresponding supported unlock datapoint. It is useful
for Home Assistant automations but is not resolved into a person's identity.
Raw credential data, ticket material, and unsupported raw unlock datapoints are
never exposed. The normalized integer can appear in the event attribute but is
never written to logs.

The first successful coordinator refresh seeds per-property timestamps without
emitting historical events. Later refreshes emit an event only when the
corresponding Tuya timestamp is newer. This permits identical values to produce
separate events when the device reports a new timestamp.

## Lock Command Flow

1. Mark the entity as locking or unlocking.
2. Request a short-lived Tuya password ticket.
3. Call the password-free door-operation endpoint with the ticket ID and the
   requested `open` value.
4. If Tuya rejects the request, clear the transition state and raise a visible
   Home Assistant error without changing the confirmed lock state.
5. If Tuya accepts the request, refresh after 2, 5, and 10 seconds, stopping as
   soon as `lock_motor_state` confirms the requested state.
6. If the final refresh does not confirm the requested state, clear the
   transition state, preserve the last confirmed state, and report that the
   command was accepted by Tuya but not physically confirmed.
7. Derive the final locked state from `lock_motor_state`; do not use a fixed
   auto-relock timer or permanently optimistic state.

## Error and Availability Behavior

- Invalid credentials stop config-entry setup with an authentication error.
- Missing, expired, or unauthorized Tuya services produce an actionable setup
  or command error where the API response distinguishes them.
- A temporarily unavailable endpoint causes a coordinator update failure. The
  last confirmed state is retained, and coordinator entities become
  unavailable until the next successful refresh.
- A failed lock command does not overwrite the last confirmed lock state.
- Unknown datapoints and undocumented enum values are tolerated and logged only
  at a non-sensitive diagnostic level.
- Logs exclude Access Secrets, access tokens, ticket IDs, ticket keys, raw
  credential payloads, and user/member identifiers from unlock events.

## Verification

Automated tests cover:

- request signing and access-token refresh;
- ticket acquisition and both door-operation values;
- command rejection and transient API failures;
- credential validation and device discovery;
- battery alias selection;
- motor-state interpretation;
- coordinator availability behavior;
- initial event suppression;
- timestamp-based repeated event generation;
- unlock-method and alarm mapping, including unknown alarm strings;
- config-flow behavior; and
- entity association with the existing Tuya device.

The repository will add a repeatable local test and lint configuration. Before
delivery, the complete automated suite and static checks must pass.

Live verification remains manual because it requires the user's Tuya account,
Home Assistant instance, and physical lock. The delivery checklist covers
service authorization, manual installation, integration setup, initial state,
battery, lock, unlock, inside-open, doorbell, alarm, and representative unlock
events.

## Delivery

The project remains a fork of `nicolasglg/tuya-smart-lock`, with the user's fork
configured as `origin` and the original repository as `upstream`. Development
occurs on a `codex/` feature branch.

Delivery includes:

- the updated integration source;
- automated tests and static checks;
- HACS metadata;
- a ready-to-copy `custom_components/tuya_smart_lock` directory; and
- setup, authorization, installation, upgrade, and live-verification
  documentation.

The initial result can be installed manually. It can later be pushed and used
as a HACS custom repository without changing the integration layout.
