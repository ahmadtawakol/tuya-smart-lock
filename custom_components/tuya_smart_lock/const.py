"""Constants for Tuya Smart Lock."""

from homeassistant.const import Platform

DOMAIN = "tuya_smart_lock"

CONFIRMATION_DELAYS = (2, 3, 5)

PLATFORMS = (
    Platform.LOCK,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.EVENT,
)

CONF_ACCESS_ID = "access_id"
CONF_ACCESS_SECRET = "access_secret"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_API_REGION = "api_region"
CONF_TUYA_ENTRY_ID = "tuya_entry_id"

API_REGIONS = {
    "eu": "openapi.tuyaeu.com",
    "us": "openapi.tuyaus.com",
    "cn": "openapi.tuyacn.com",
    "in": "openapi.tuyain.com",
}

# Tuya device categories that are locks / access control
LOCK_CATEGORIES = {
    "mk",  # Access control
    "ms",  # Smart lock
    "jtmsbh",  # Smart lock (legacy)
    "jtmspro",  # Smart lock pro
    "gyms",  # Gym locker
    "hotelms",  # Hotel lock
    "videolock",  # Video lock
    "photolock",  # Photo lock
}

TICKET_ENDPOINT = "/v1.0/devices/{device_id}/door-lock/password-ticket"
DOOR_OPERATE_ENDPOINT = (
    "/v1.0/smart-lock/devices/{device_id}/password-free/door-operate"
)
SHADOW_PROPERTIES_ENDPOINT = "/v2.0/cloud/thing/{device_id}/shadow/properties"
REMOTE_UNLOCKS_ENDPOINT = "/v1.0/devices/{device_id}/door-lock/remote-unlocks"

UNLOCK_EVENT_TYPES_BY_CODE = {
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

EVENT_SOURCE_CODES = frozenset(
    {"doorbell", "open_inside", "alarm_lock", *UNLOCK_EVENT_TYPES_BY_CODE}
)
