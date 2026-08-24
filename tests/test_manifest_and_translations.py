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
HACS_MY_LINK = (
    "https://my.home-assistant.io/redirect/hacs_repository/"
    "?owner=ahmadtawakol&repository=tuya-smart-lock&category=integration"
)


def _load_json(path: Path) -> dict:
    """Load a repository JSON document."""
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def test_manifest_describes_release_and_fork_ownership() -> None:
    """The integration manifest publishes the intended release metadata."""
    manifest = _load_json(INTEGRATION / "manifest.json")

    assert manifest["version"] == "1.2.3"
    assert manifest["integration_type"] == "device"
    assert manifest["iot_class"] == "cloud_push"
    assert manifest["config_flow"] is True
    assert manifest["documentation"] == REPOSITORY
    assert manifest["issue_tracker"] == f"{REPOSITORY}/issues"
    assert manifest["codeowners"] == ["@nicolasglg", "@ahmadtawakol"]
    assert manifest["after_dependencies"] == ["tuya"]
    assert manifest["requirements"] == []


def test_readme_publishes_hacs_custom_repository_installation() -> None:
    """The README describes the published HACS custom-repository flow."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    hacs_section = readme.split("### HACS custom repository (recommended)", maxsplit=1)[
        1
    ].split("### Manual", maxsplit=1)[0]
    hacs_badge = (
        "[![Open your Home Assistant instance and add this repository to HACS.]"
        "(https://my.home-assistant.io/badges/hacs_repository.svg)]"
        f"({HACS_MY_LINK})"
    )

    assert hacs_badge in hacs_section
    hacs_text = " ".join(hacs_section.split())

    def assert_ordered(text: str, phrases: tuple[str, ...]) -> None:
        """Assert that every phrase appears in sequence within one path."""
        cursor = 0
        for phrase in phrases:
            position = text.find(phrase, cursor)
            assert position >= 0, f"Missing or out of order: {phrase}"
            cursor = position + len(phrase)

    badge_marker = "**Badge:**"
    manual_marker = "**Manual:**"
    common_marker = "After either path"
    assert badge_marker in hacs_text
    assert manual_marker in hacs_text
    assert common_marker in hacs_text

    badge_path = hacs_text.split(badge_marker, maxsplit=1)[1].split(
        manual_marker, maxsplit=1
    )[0]
    manual_path = hacs_text.split(manual_marker, maxsplit=1)[1].split(
        common_marker, maxsplit=1
    )[0]
    common_path = hacs_text.split(common_marker, maxsplit=1)[1].split(
        "Future published releases appear as updates in HACS.", maxsplit=1
    )[0]
    update_path = hacs_text.split(
        "Future published releases appear as updates in HACS.", maxsplit=1
    )[1]

    assert_ordered(
        badge_path,
        (
            "Select the button above",
            "opens the Tuya Smart Lock repository directly in HACS",
            "Skip the custom-repository URL, type, and **Add** dialog",
            "**Download**",
        ),
    )
    assert_ordered(
        manual_path,
        (
            "Open HACS",
            "upper-right three-dot menu",
            "**Custom repositories**",
            REPOSITORY,
            "**Integration**",
            "**Add**",
            "open **Tuya Smart Lock** in HACS",
        ),
    )
    assert_ordered(
        common_path,
        (
            "Tuya Smart Lock repository page",
            "**Download**",
            "Restart Home Assistant",
            "Settings > Devices & services",
        ),
    )
    assert_ordered(
        update_path,
        (
            "**Settings > Updates**",
            "**Install**",
            "**Pending update** status",
            "three-dot menu",
            "**Redownload**",
            "restart Home Assistant afterward",
        ),
    )

    assert "Home Assistant 2026.7.2 or newer" in hacs_text
    assert "**Pending updates**" not in hacs_text
    assert (
        "This repository is installed as a HACS custom repository; "
        "it is not listed in the HACS default catalog."
    ) in hacs_text
    assert "not installable from HACS yet" not in readme
    assert "Neither default-branch publication" not in readme
    assert "available in the HACS default catalog" not in readme
    assert "included in the HACS default catalog" not in readme
    assert "included in HACS defaults" not in readme


def test_hacs_metadata_requires_supported_home_assistant_release() -> None:
    """HACS metadata retains its shape and pins the supported HA minimum."""
    metadata = _load_json(ROOT / "hacs.json")

    assert metadata == {
        "name": "Tuya Smart Lock",
        "homeassistant": "2026.7.2",
        "render_readme": True,
    }


def test_readme_defaults_to_free_app_auth_and_scopes_verified_control() -> None:
    """Docs keep free auth and limit verified control to the tested model."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    prerequisites = readme.split("## Prerequisites", maxsplit=1)[1].split(
        "## Installation", maxsplit=1
    )[0]
    configuration = readme.split("## Configuration", maxsplit=1)[1].split(
        "## Runtime behavior", maxsplit=1
    )[0]
    normalized_readme = " ".join(readme.split())

    assert "built-in **Tuya** integration" in prerequisites
    assert "QR-code app login" in prerequisites
    assert "IoT Core" not in prerequisites
    assert "Access ID" not in prerequisites
    assert "No Tuya developer subscription is required" in normalized_readme
    assert "Control in `v1.2.0` is physically verified" in normalized_readme
    assert "Control remains experimental for other models" in normalized_readme
    assert "reports success only after the physical state" in normalized_readme
    assert "Reconfigure" in configuration
    assert "Access ID, Access Secret" in configuration


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


def test_user_description_uses_free_official_tuya_session() -> None:
    """The default setup no longer requests developer cloud credentials."""
    expected = (
        "This integration reuses Home Assistant's official Tuya app login. "
        "No Tuya developer subscription is required."
    )
    strings = _load_json(INTEGRATION / "strings.json")
    english = _load_json(INTEGRATION / "translations" / "en.json")

    assert strings["config"]["step"]["user"]["description"] == expected
    assert english["config"]["step"]["user"]["description"] == expected
    assert "Access ID" not in expected
    assert "Access Secret" not in expected


def test_config_translations_retain_all_supported_flow_messages() -> None:
    """All config-flow fields, errors, and abort reasons remain translated."""
    strings = _load_json(INTEGRATION / "strings.json")
    config = strings["config"]

    assert set(config["step"]) == {
        "user",
        "select_device",
        "reauth_confirm",
        "reconfigure_confirm",
    }
    assert "data" not in config["step"]["user"]
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
        "already_using_official_tuya",
        "migration_device_not_found",
        "no_devices_found",
        "official_tuya_reauth_started",
        "reconfigure_successful",
        "reauth_successful",
        "tuya_not_configured",
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
