"""Typed exceptions raised by the Tuya Smart Lock integration."""


class TuyaApiError(Exception):
    """Base exception for safe Tuya API failures."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        """Initialize an API error with an optional Tuya error code."""
        super().__init__(message)
        self.code = code


class TuyaAuthenticationError(TuyaApiError):
    """Raised when Tuya rejects the configured credentials."""


class TuyaAuthorizationError(TuyaApiError):
    """Raised when credentials lack permission for an operation."""


class TuyaRateLimitError(TuyaApiError):
    """Raised when Tuya rate-limits an API request."""


class TuyaCommandError(TuyaApiError):
    """Raised when Tuya rejects a lock command."""


class TuyaDeviceUnavailableError(TuyaCommandError):
    """Raised when Tuya reports that a command target is unavailable."""
