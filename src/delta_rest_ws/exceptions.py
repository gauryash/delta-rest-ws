"""SDK-specific exceptions."""

from typing import Any, Mapping, Optional


class DeltaError(Exception):
    """Base class for all SDK errors."""


class DeltaAuthenticationError(DeltaError):
    """Raised when credentials are missing or rejected."""


class DeltaHTTPError(DeltaError):
    """Raised for a non-successful HTTP status."""

    def __init__(self, message: str, status_code: int, response: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class DeltaAPIError(DeltaError):
    """Raised when Delta returns a successful HTTP response with an API error."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        context: Optional[Mapping[str, Any]] = None,
        response: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = context
        self.response = response


class DeltaWebSocketError(DeltaError):
    """Raised for WebSocket connection, protocol, or authentication errors."""
