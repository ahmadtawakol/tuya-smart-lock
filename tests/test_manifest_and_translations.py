"""Release metadata and translation contract tests."""

import json
from pathlib import Path

import yaml

from custom_components.tuya_smart_lock.binary_sensor import (
    TuyaSmartLockHijackBinarySensor,
)
from custom_components.tuya_smart_lock.event import (
    TuyaSmartLockAlarmEvent,
    TuyaSmartLockDoorbellEvent,
    TuyaSmartLockOpenedInsideEvent,
    TuyaSmartLockUnlockEvent,
)
from custom_components.tuya_smart_lock.lock import TuyaSmartLock
from custom_components.tuya_smart_lock.sensor import TuyaSmartLockBatterySensor

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "tuya_smart_lock"
REPOSITORY = "https://github.com/ahmadtawakol/tuya-smart-lock"


def _load_json(path: Path) -> dict:
    """Load a repository JSON document."""
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_manifest_describes_release_and_fork_ownership() -> None:
    """The integration manifest publishes the intended release metadata."""
    manifest = _load_json(INTEGRATION / "manifest.json")

    assert manifest["version"] == "1.1.0"
    assert manifest["integration_type"] == "device"
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["config_flow"] is True
    assert manifest["documentation"] == REPOSITORY
    assert manifest["issue_tracker"] == f"{REPOSITORY}/issues"
    assert manifest["codeowners"] == ["@nicolasglg", "@ahmadtawakol"]
    assert manifest["requirements"] == []


def test_hacs_metadata_requires_supported_home_assistant_release() -> None:
    """HACS metadata retains its shape and pins the supported HA minimum."""
    metadata = _load_json(ROOT / "hacs.json")

    assert metadata == {
        "name": "Tuya Smart Lock",
        "homeassistant": "2026.7.2",
        "render_readme": True,
    }


def test_ci_runs_tests_hacs_validation_and_hassfest() -> None:
    """CI validates Python, HACS integration metadata, and HA metadata."""
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    )

    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"test", "hacs", "hassfest"}

    hacs_steps = workflow["jobs"]["hacs"]["steps"]
    assert {step.get("uses") for step in hacs_steps} >= {
        "actions/checkout@v4",
        "hacs/action@main",
    }
    hacs_action = next(
        step for step in hacs_steps if step.get("uses") == "hacs/action@main"
    )
    assert hacs_action["with"] == {"category": "integration"}

    hassfest_steps = workflow["jobs"]["hassfest"]["steps"]
    assert {step.get("uses") for step in hassfest_steps} >= {
        "actions/checkout@v4",
        "home-assistant/actions/hassfest@master",
    }


def test_english_translation_has_exact_strings_parity() -> None:
    """The source strings and English translation cannot drift apart."""
    strings = _load_json(INTEGRATION / "strings.json")
    english = _load_json(INTEGRATION / "translations" / "en.json")

    assert english == strings


def test_config_translations_retain_all_supported_flow_messages() -> None:
    """All config-flow fields, errors, and abort reasons remain translated."""
    strings = _load_json(INTEGRATION / "strings.json")
    config = strings["config"]

    assert set(config["step"]) == {"user", "select_device", "reauth_confirm"}
    assert set(config["step"]["user"]["data"]) == {
        "access_id",
        "access_secret",
        "api_region",
    }
    assert set(config["step"]["select_device"]["data"]) == {"device_id"}
    assert set(config["step"]["reauth_confirm"]["data"]) == {
        "access_id",
        "access_secret",
        "api_region",
    }
    assert set(config["error"]) == {
        "invalid_auth",
        "service_not_authorized",
        "rate_limited",
        "cannot_connect",
        "remote_unlock_disabled",
    }
    assert set(config["abort"]) == {
        "already_configured",
        "no_devices_found",
        "reauth_successful",
    }


def test_entity_translations_are_complete_and_used_by_production_classes() -> None:
    """Every shipped entity uses one matching, live English translation key."""
    strings = _load_json(INTEGRATION / "strings.json")
    expected = {
        "lock": {"lock": {"name": "Lock"}},
        "sensor": {"battery": {"name": "Battery"}},
        "binary_sensor": {"duress": {"name": "Duress"}},
        "event": {
            "doorbell": {"name": "Doorbell"},
            "opened_inside": {"name": "Opened inside"},
            "lock_alarm": {"name": "Lock alarm"},
            "unlocked": {"name": "Unlocked"},
        },
    }
    production_classes = {
        "lock": {"lock": TuyaSmartLock},
        "sensor": {"battery": TuyaSmartLockBatterySensor},
        "binary_sensor": {"duress": TuyaSmartLockHijackBinarySensor},
        "event": {
            "doorbell": TuyaSmartLockDoorbellEvent,
            "opened_inside": TuyaSmartLockOpenedInsideEvent,
            "lock_alarm": TuyaSmartLockAlarmEvent,
            "unlocked": TuyaSmartLockUnlockEvent,
        },
    }

    assert strings["entity"] == expected
    assert set(production_classes) == set(expected)
    for platform, classes in production_classes.items():
        assert set(classes) == set(expected[platform])
        for translation_key, entity_class in classes.items():
            assert entity_class.__dict__["__attr_translation_key"] == translation_key
            assert "_attr_name" not in entity_class.__dict__


def test_command_exception_translations_are_complete_and_fixed() -> None:
    """Every command failure category has a fixed public translation."""
    strings = _load_json(INTEGRATION / "strings.json")

    assert strings["exceptions"] == {
        "command_authentication_failed": {
            "message": (
                "Tuya Cloud authentication failed. Reauthentication has been requested."
            )
        },
        "command_not_authorized": {
            "message": "Tuya Cloud is not authorized to operate this lock."
        },
        "command_rate_limited": {
            "message": "Tuya Cloud is temporarily rate limited. Try again later."
        },
        "command_device_unavailable": {
            "message": "The Tuya smart lock is offline or unavailable."
        },
        "command_rejected": {"message": "Tuya rejected the smart lock command."},
        "command_connection_failed": {
            "message": "Unable to communicate with Tuya Cloud."
        },
        "command_confirmation_timeout": {
            "message": (
                "Tuya accepted the lock command but the physical state "
                "was not confirmed."
            )
        },
    }
