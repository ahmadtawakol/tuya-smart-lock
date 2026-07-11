# Tuya Video Lock Control and Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Tuya Smart Lock custom integration to provide confirmed lock/unlock control and timestamp-aware telemetry for Tuya `videolock` devices.

**Architecture:** A Home Assistant-managed HTTP session feeds a typed Tuya Cloud API client. One `DataUpdateCoordinator` polls shadow properties for all coordinator-backed lock, sensor, binary-sensor, and event entities; commands use Tuya's ticket flow and bounded state confirmation.

**Tech Stack:** Python 3.14, Home Assistant 2026.7.2 custom integrations, `aiohttp`, `DataUpdateCoordinator`, `pytest-homeassistant-custom-component`, pytest, Ruff, GitHub Actions.

**Design reference:** `docs/superpowers/specs/2026-07-11-videolock-control-telemetry-design.md`

---

## File Map

- `pyproject.toml`: Python, pytest, and Ruff configuration for repeatable local checks.
- `.github/workflows/tests.yml`: CI for tests and linting.
- `custom_components/tuya_smart_lock/const.py`: endpoints, intervals, platform list, and normalized unlock mappings.
- `custom_components/tuya_smart_lock/errors.py`: safe, typed API exceptions.
- `custom_components/tuya_smart_lock/models.py`: shadow-property model and timestamp normalization.
- `custom_components/tuya_smart_lock/tuya_api.py`: signing, token lifecycle, discovery, property reads, and ticket operations.
- `custom_components/tuya_smart_lock/coordinator.py`: shared polling and API-to-Home-Assistant error translation.
- `custom_components/tuya_smart_lock/entity.py`: common coordinator entity and Tuya device association.
- `custom_components/tuya_smart_lock/__init__.py`: session, API, coordinator, first refresh, and platform lifecycle.
- `custom_components/tuya_smart_lock/config_flow.py`: validation, discovery, and actionable setup errors.
- `custom_components/tuya_smart_lock/lock.py`: coordinator-backed lock state and confirmed command flow.
- `custom_components/tuya_smart_lock/sensor.py`: battery percentage with alias fallback.
- `custom_components/tuya_smart_lock/binary_sensor.py`: hijack/duress safety state.
- `custom_components/tuya_smart_lock/event.py`: doorbell, inside-open, alarm, and unlock events.
- `custom_components/tuya_smart_lock/manifest.json`: compatibility and fork metadata.
- `custom_components/tuya_smart_lock/strings.json`: setup and entity strings.
- `custom_components/tuya_smart_lock/translations/en.json`: English translations mirroring `strings.json`.
- `tests/`: focused API, coordinator, flow, and entity tests.
- `README.md`: authorization, installation, entities, limitations, and troubleshooting.
- `docs/live-verification.md`: physical-device verification checklist.

## Task 1: Establish the Test Harness and Property Model

Use `@superpowers:test-driven-development` for every production change in this
plan.

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_models.py`
- Create: `custom_components/tuya_smart_lock/errors.py`
- Create: `custom_components/tuya_smart_lock/models.py`

- [ ] **Step 1: Add the test and lint configuration**

Create this minimum `pyproject.toml` (the executor may raise dependency lower
bounds only if installation proves a current package requires it):

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "tuya-smart-lock"
version = "1.1.0"
requires-python = ">=3.14"
dependencies = []

[project.optional-dependencies]
test = [
  "homeassistant==2026.7.2",
  "pytest>=8.3",
  "pytest-homeassistant-custom-component>=0.13.0",
  "ruff>=0.11",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py314"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ASYNC"]
```

Add `.venv/`, `__pycache__/`, `.pytest_cache/`, and `.ruff_cache/` to
`.gitignore`. Add the plugin and required custom-integration enablement fixture
to `tests/conftest.py`:

```python
import pytest


pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow Home Assistant to load this custom integration in every test."""
    yield
```

- [ ] **Step 2: Create the isolated development environment**

Run:

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
```

Expected: installation succeeds with Home Assistant 2026.7.2 importable from
`.venv/bin/python`.

- [ ] **Step 3: Write failing property-model tests**

In `tests/test_models.py`, cover milliseconds, seconds, malformed timestamps,
invalid property records, and duplicate codes:

```python
from custom_components.tuya_smart_lock.models import (
    normalize_timestamp_ms,
    properties_by_code,
)


def test_normalize_timestamp_ms() -> None:
    assert normalize_timestamp_ms(1_783_792_375_000) == 1_783_792_375_000
    assert normalize_timestamp_ms(1_783_792_375) == 1_783_792_375_000
    assert normalize_timestamp_ms(None) is None
    assert normalize_timestamp_ms("bad") is None
    assert normalize_timestamp_ms(True) is None


def test_properties_by_code_keeps_latest_duplicate() -> None:
    payload = {
        "result": {
            "properties": [
                {"code": "doorbell", "dp_id": 53, "time": 10, "value": False},
                {"code": "doorbell", "dp_id": 53, "time": 20, "value": True},
                {"dp_id": 99, "time": 20, "value": "ignored"},
            ]
        }
    }

    properties = properties_by_code(payload)

    assert properties["doorbell"].value is True
    assert properties["doorbell"].timestamp_ms == 20_000
    assert set(properties) == {"doorbell"}
```

- [ ] **Step 4: Run the model tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_models.py -q`

Expected: FAIL because `models.py` does not exist.

- [ ] **Step 5: Implement the minimal model and exception types**

Implement an immutable `TuyaProperty` dataclass with `code`, `value`,
`timestamp_ms`, and `dp_id`. `normalize_timestamp_ms` must reject booleans,
negative values, and non-numeric values; values below `100_000_000_000` are
seconds and are multiplied by 1000. `properties_by_code` must safely traverse
`result.properties`, ignore records without a non-empty string code, and keep
the last duplicate.

Create typed exceptions without embedding credentials, tokens, tickets, or
response bodies:

```python
class TuyaApiError(Exception):
    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class TuyaAuthenticationError(TuyaApiError): ...
class TuyaAuthorizationError(TuyaApiError): ...
class TuyaRateLimitError(TuyaApiError): ...
class TuyaCommandError(TuyaApiError): ...
```

- [ ] **Step 6: Run the model tests and lint**

Run: `.venv/bin/python -m pytest tests/test_models.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check custom_components tests`

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add .gitignore pyproject.toml tests custom_components/tuya_smart_lock/errors.py custom_components/tuya_smart_lock/models.py
git commit -m "test: establish Tuya lock test harness"
```

## Task 2: Refactor the Tuya API Client Around a Shared Session

**Files:**
- Modify: `custom_components/tuya_smart_lock/const.py`
- Modify: `custom_components/tuya_smart_lock/tuya_api.py`
- Create: `tests/test_tuya_api.py`

- [ ] **Step 1: Write failing signing and token tests**

Use the Home Assistant `aioclient_mock` fixture and freeze `time.time`. Verify:

- token requests contain the expected HMAC-SHA256 signature inputs;
- a cached unexpired token avoids a second token request;
- an expired token refreshes;
- the client uses the injected Home Assistant session rather than constructing
  `aiohttp.ClientSession`;
- logged and raised errors exclude Access Secret, token, ticket, and raw body.

- [ ] **Step 2: Run the focused API tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_tuya_api.py -q`

Expected: FAIL because the existing constructor does not accept a session and
creates a new session for each request.

- [ ] **Step 3: Inject the session and centralize response handling**

Change the constructor contract to:

```python
def __init__(
    self,
    session: aiohttp.ClientSession,
    access_id: str,
    access_secret: str,
    region: str = "eu",
) -> None:
```

Use `session.request(method, url, headers=headers, data=body_str or None)` and
one canonical compact body serialization (`separators=(",", ":")`) for both
signing and transmission. Add `_raise_for_response` that maps token failures to
`TuyaAuthenticationError`, permission/subscription failures to
`TuyaAuthorizationError`, rate-limit failures to `TuyaRateLimitError`, and all
other unsuccessful responses to `TuyaApiError`. Error messages may include only
the Tuya error code and sanitized message.

- [ ] **Step 4: Write failing operation and shadow-property tests**

Cover these exact endpoints and contracts:

```text
GET  /v2.0/cloud/thing/{device_id}/shadow/properties
POST /v1.0/devices/{device_id}/door-lock/password-ticket
POST /v1.0/smart-lock/devices/{device_id}/password-free/door-operate
```

Assert that lock sends `{"ticket_id": "ticket", "open": false}`, unlock sends
`{"ticket_id": "ticket", "open": true}`, and shadow reads return the normalized
mapping from Task 1. Also cover missing `ticket_id`, command rejection, invalid
auth, permission denial, and rate limiting.

- [ ] **Step 5: Implement the API methods**

Expose these public methods:

```python
async def async_validate_credentials(self) -> None: ...
async def async_discover_devices(self) -> list[dict[str, str]]: ...
async def async_check_remote_unlock(self, device_id: str) -> bool: ...
async def async_get_properties(self, device_id: str) -> dict[str, TuyaProperty]: ...
async def async_operate_lock(self, device_id: str, *, open_: bool) -> None: ...
```

Remove `async_get_auto_lock_time`, `async_get_lock_state`, `async_lock`, and
`async_unlock`; their responsibilities are replaced by shadow polling and the
single typed operation method.

- [ ] **Step 6: Run the API suite and lint**

Run: `.venv/bin/python -m pytest tests/test_tuya_api.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check custom_components/tuya_smart_lock/tuya_api.py tests/test_tuya_api.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add custom_components/tuya_smart_lock/const.py custom_components/tuya_smart_lock/tuya_api.py tests/test_tuya_api.py
git commit -m "refactor: add typed Tuya cloud client"
```

## Task 3: Add the Shared Coordinator and Integration Lifecycle

**Files:**
- Create: `custom_components/tuya_smart_lock/coordinator.py`
- Create: `custom_components/tuya_smart_lock/entity.py`
- Modify: `custom_components/tuya_smart_lock/__init__.py`
- Modify: `custom_components/tuya_smart_lock/const.py`
- Create: `tests/test_coordinator.py`
- Create: `tests/test_init.py`

- [ ] **Step 1: Write failing coordinator tests**

Test a successful refresh, API failure, authentication failure, and unavailable
recovery. Assert that API failures become `UpdateFailed`, authentication
failures become `ConfigEntryAuthFailed`, and valid data remains a
`dict[str, TuyaProperty]`.

- [ ] **Step 2: Run coordinator tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_coordinator.py -q`

Expected: FAIL because `TuyaSmartLockCoordinator` does not exist.

- [ ] **Step 3: Implement the coordinator and base entity**

Create a coordinator with:

```python
super().__init__(
    hass,
    _LOGGER,
    config_entry=entry,
    name=DOMAIN,
    update_interval=timedelta(seconds=30),
)
```

Its `_async_update_data` calls `api.async_get_properties(device_id)` and maps
typed API exceptions without including property values in log messages.

Create `TuyaSmartLockEntity(CoordinatorEntity[TuyaSmartLockCoordinator])` with
common unique-ID construction, `has_entity_name = True`, and device info:

```python
DeviceInfo(
    identifiers={("tuya", device_id)},
    name=device_name,
    manufacturer="Tuya",
)
```

- [ ] **Step 4: Write failing setup and unload tests**

Assert that setup obtains `async_get_clientsession(hass)`, constructs the API
and coordinator, performs `async_config_entry_first_refresh`, stores a typed
runtime object, and forwards exactly `LOCK`, `SENSOR`, `BINARY_SENSOR`, and
`EVENT`. Assert unload removes runtime data.

- [ ] **Step 5: Implement setup and lifecycle**

Use a small dataclass for runtime data instead of the current untyped nested
dictionary. Define platforms once in `const.py` and use them for setup and
unload. Pass the config entry explicitly to the coordinator for Home Assistant
2026.8 compatibility.

- [ ] **Step 6: Run setup/coordinator tests and lint**

Run: `.venv/bin/python -m pytest tests/test_coordinator.py tests/test_init.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check custom_components tests`

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add custom_components/tuya_smart_lock tests/test_coordinator.py tests/test_init.py
git commit -m "feat: add shared Tuya lock coordinator"
```

## Task 4: Make the Config Flow Actionable and Safe

**Files:**
- Modify: `custom_components/tuya_smart_lock/config_flow.py`
- Modify: `custom_components/tuya_smart_lock/strings.json`
- Modify: `custom_components/tuya_smart_lock/translations/en.json`
- Create: `tests/test_config_flow.py`

- [ ] **Step 1: Write failing config-flow tests**

Cover valid credentials, invalid credentials, cannot-connect, missing service
authorization, rate limiting, no devices, remote control disabled, device
selection, and duplicate device abort. Verify the Access Secret is stored only
in entry data and never appears in titles, placeholders, or logs.

- [ ] **Step 2: Run config-flow tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_config_flow.py -q`

Expected: FAIL because the flow currently collapses failures to booleans and
constructs its own HTTP session.

- [ ] **Step 3: Implement typed flow handling**

Use `async_get_clientsession(self.hass)` when constructing the API. Map:

```text
TuyaAuthenticationError -> invalid_auth
TuyaAuthorizationError  -> service_not_authorized
TuyaRateLimitError      -> rate_limited
TuyaApiError/aiohttp     -> cannot_connect
```

Keep device discovery lazy, set the unique ID before entry creation, and do not
assume remote unlock is enabled when its permission check fails.

- [ ] **Step 4: Add matching user-facing strings**

Add `service_not_authorized` and `rate_limited`, and keep `strings.json` and
`translations/en.json` structurally identical. The authorization message must
direct the user to authorize IoT Core and Smart Lock Open Service without
echoing Tuya's raw response. The rate-limit message must tell the user to wait
and retry without claiming their credentials are invalid.

- [ ] **Step 5: Run flow tests and lint**

Run: `.venv/bin/python -m pytest tests/test_config_flow.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check custom_components/tuya_smart_lock/config_flow.py tests/test_config_flow.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add custom_components/tuya_smart_lock/config_flow.py custom_components/tuya_smart_lock/strings.json custom_components/tuya_smart_lock/translations/en.json tests/test_config_flow.py
git commit -m "feat: report actionable Tuya setup errors"
```

## Task 5: Replace Optimistic Lock State With Physical Confirmation

**Files:**
- Modify: `custom_components/tuya_smart_lock/lock.py`
- Modify: `custom_components/tuya_smart_lock/const.py`
- Create: `tests/test_lock.py`

- [ ] **Step 1: Write failing lock-state tests**

Verify `lock_motor_state=True` renders unlocked,
`lock_motor_state=False` renders locked, missing or non-boolean state renders
unknown, and coordinator availability controls entity availability. Preserve
the existing unique ID `tuya_smart_lock_{device_id}` to avoid entity churn.

- [ ] **Step 2: Write failing command tests**

For both lock and unlock, assert:

- the correct `open_` value is sent;
- locking/unlocking transition state is visible;
- refreshes happen at cumulative 2, 5, and 10 seconds and stop early on
  confirmation;
- second-to-millisecond timestamp handling is unaffected by confirmation;
- a rejected operation preserves the confirmed state and raises
  `HomeAssistantError`;
- a transient command API or rate-limit failure preserves the confirmed state
  and raises a sanitized `HomeAssistantError`;
- a failed confirmation refresh cannot confirm from retained stale coordinator
  data, even when that stale value matches the requested state;
- a failed early refresh followed by a successful matching refresh confirms;
- an accepted but unconfirmed operation raises a distinct visible error after
  the final refresh.

Patch `asyncio.sleep` in tests so no wall-clock waiting occurs.

- [ ] **Step 3: Run lock tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_lock.py -q`

Expected: FAIL because the existing entity is optimistic and uses a fixed
auto-relock timer.

- [ ] **Step 4: Implement coordinator-backed state and bounded confirmation**

Replace the timer and direct API reference. Use `CONFIRMATION_DELAYS = (2, 3,
5)` to reach cumulative checks at 2, 5, and 10 seconds. After each delay call
`coordinator.async_refresh()`. Stop only when `coordinator.last_update_success`
is true and the newly refreshed `lock_motor_state` matches the requested
unlocked state. A failed refresh retains old data, so it must never confirm a
command. Use `try/finally` to clear transition flags and translate typed API
errors to sanitized `HomeAssistantError` instances.

- [ ] **Step 5: Run lock tests and lint**

Run: `.venv/bin/python -m pytest tests/test_lock.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check custom_components/tuya_smart_lock/lock.py tests/test_lock.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 5**

```bash
git add custom_components/tuya_smart_lock/lock.py custom_components/tuya_smart_lock/const.py tests/test_lock.py
git commit -m "feat: confirm Tuya lock command state"
```

## Task 6: Add Battery and Duress Entities

**Files:**
- Create: `custom_components/tuya_smart_lock/sensor.py`
- Create: `custom_components/tuya_smart_lock/binary_sensor.py`
- Create: `tests/test_sensor.py`
- Create: `tests/test_binary_sensor.py`

- [ ] **Step 1: Write failing battery tests**

Assert that `battery_percentage` takes precedence over
`residual_electricity`, the fallback works, numeric values are clamped only by
Home Assistant display metadata (not silently rewritten), invalid values render
unknown, and the entity uses battery device class, percent units, and a stable
`{device_id}_battery` unique ID.

- [ ] **Step 2: Write failing hijack tests**

Assert that `hijack=True` is on, `False` is off, missing/non-boolean is unknown,
the device class is safety, and the stable unique ID is
`{device_id}_hijack`.

- [ ] **Step 3: Run telemetry tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_sensor.py tests/test_binary_sensor.py -q`

Expected: FAIL because the platform modules do not exist.

- [ ] **Step 4: Implement the two coordinator platforms**

Use `SensorDeviceClass.BATTERY`, `PERCENTAGE`, and
`SensorStateClass.MEASUREMENT` for battery. Use
`BinarySensorDeviceClass.SAFETY` for hijack. Both entities inherit the common
base entity and read only `coordinator.data`.

- [ ] **Step 5: Run telemetry tests and lint**

Run: `.venv/bin/python -m pytest tests/test_sensor.py tests/test_binary_sensor.py -q`

Expected: PASS.

Run: `.venv/bin/python -m ruff check custom_components tests/test_sensor.py tests/test_binary_sensor.py`

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add custom_components/tuya_smart_lock/sensor.py custom_components/tuya_smart_lock/binary_sensor.py tests/test_sensor.py tests/test_binary_sensor.py
git commit -m "feat: add Tuya lock safety telemetry"
```

## Task 7: Add Timestamp-Aware Event Entities

**Files:**
- Create: `custom_components/tuya_smart_lock/event.py`
- Modify: `custom_components/tuya_smart_lock/const.py`
- Create: `tests/test_event.py`

- [ ] **Step 1: Write failing event-seeding tests**

For every event entity, assert that the first successful coordinator data seeds
timestamps without emitting. Missing or malformed timestamps must not emit and
must not advance the cursor.

- [ ] **Step 2: Write failing doorbell and inside-open tests**

Assert a newer timestamp emits exactly once even when the boolean value remains
unchanged. The doorbell must use `EventDeviceClass.DOORBELL`, declare
`DoorbellEventType.RING`, and emit `ring`. Inside-open emits `opened`.

- [ ] **Step 3: Write failing alarm and unlock tests**

Alarm must always emit event type `alarm` with arbitrary strings such as
`alarm_illegal_user` in the `reason` attribute. Unlock must implement this
fixed mapping:

```python
UNLOCK_EVENT_TYPES = {
    "unlock_password": "password",
    "unlock_fingerprint": "fingerprint",
    "unlock_card": "card",
    "unlock_face": "face",
    "unlock_hand": "palm",
    "unlock_temporary": "temporary_code",
    "unlock_key": "physical_key",
    "unlock_phone_remote": "phone_remote",
    "unlock_dynamic": "dynamic_code",
}
```

Assert `credential_id` accepts integers only, appears in event attributes, and
never appears in captured logs. Verify two codes advancing in one refresh each
trigger an entity update in deterministic timestamp/code order.

- [ ] **Step 4: Run event tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_event.py -q`

Expected: FAIL because `event.py` does not exist.

- [ ] **Step 5: Implement event entities**

Create a timestamp-event base that seeds its cursor in `async_added_to_hass`,
checks newer timestamps in `_handle_coordinator_update`, calls `_trigger_event`,
then calls `async_write_ha_state`. Do not log property values. Add four entities:

```text
{device_id}_doorbell
{device_id}_opened_inside
{device_id}_lock_alarm
{device_id}_unlocked
```

The multi-code unlock entity keeps one cursor per supported datapoint and
declares the complete fixed event-type list.

- [ ] **Step 6: Run event tests and lint**

Run: `.venv/bin/python -m pytest tests/test_event.py -q`

Expected: PASS, including the explicit standard `ring` assertion.

Run: `.venv/bin/python -m ruff check custom_components/tuya_smart_lock/event.py tests/test_event.py`

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```bash
git add custom_components/tuya_smart_lock/event.py custom_components/tuya_smart_lock/const.py tests/test_event.py
git commit -m "feat: add Tuya lock event telemetry"
```

## Task 8: Finish Metadata, Documentation, CI, and Full Verification

**Files:**
- Modify: `custom_components/tuya_smart_lock/manifest.json`
- Modify: `custom_components/tuya_smart_lock/strings.json`
- Modify: `custom_components/tuya_smart_lock/translations/en.json`
- Modify: `hacs.json`
- Modify: `README.md`
- Create: `docs/live-verification.md`
- Create: `.github/workflows/tests.yml`
- Create: `tests/test_manifest_and_translations.py`

- [ ] **Step 1: Write failing metadata and translation tests**

Assert manifest version `1.1.0`, `cloud_polling`, documentation and issue links
to `ahmadtawakol/tuya-smart-lock`, the `hacs.json` Home Assistant minimum
`2026.7.2`, and exact structural parity between `strings.json` and
`translations/en.json`. Assert entity translation keys exist for lock, battery,
hijack, doorbell, opened-inside, alarm, and unlocked.

- [ ] **Step 2: Run metadata tests and verify failure**

Run: `.venv/bin/python -m pytest tests/test_manifest_and_translations.py -q`

Expected: FAIL because metadata and entity translations are still at v1.0.0.

- [ ] **Step 3: Update metadata and user-facing strings**

Keep the original maintainer in `codeowners` and add `@ahmadtawakol`. Set HACS
minimum Home Assistant to `2026.7.2`. Add localized entity names and all new
errors while keeping both translation files identical.

- [ ] **Step 4: Rewrite the README and live checklist**

Document:

- why an official Tuya handler quirk cannot add the missing lock platform;
- IoT Core and Smart Lock Open Service authorization;
- account linking, remote-control enablement, and US API region for the target
  diagnostic;
- HACS custom repository `ahmadtawakol/tuya-smart-lock` and manual copying;
- every entity and its semantics;
- 30-second polling and possible event collapsing;
- credential and `credential_id` privacy behavior;
- expired service, permission, region, unavailable device, and unconfirmed
  command troubleshooting.

Create `docs/live-verification.md` with checkboxes for setup, initial state,
battery, physical lock/unlock, Home Assistant lock/unlock, inside-open,
doorbell, alarm, and representative unlock methods. Do not include credentials
or the diagnostic's device ID.

- [ ] **Step 5: Add CI**

Create a GitHub Actions workflow for Python 3.14 that installs `.[test]` and
runs:

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

- [ ] **Step 6: Run the complete verification suite**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests PASS with no warnings attributable to this integration.

Run: `.venv/bin/python -m ruff check .`

Expected: PASS.

Run: `.venv/bin/python -m ruff format --check .`

Expected: PASS.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 7: Commit Task 8**

```bash
git add .github README.md docs/live-verification.md hacs.json pyproject.toml custom_components tests
git commit -m "docs: prepare Tuya videolock release"
```

- [ ] **Step 8: Perform the completion review**

Invoke `@superpowers:requesting-code-review`, resolve any important findings,
then invoke `@superpowers:verification-before-completion` and rerun the full
verification commands before claiming completion or publishing.

Do not push, publish a release, or open a pull request until the user explicitly
selects that integration option.
