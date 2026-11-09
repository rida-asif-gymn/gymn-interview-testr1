from __future__ import annotations

from typing import Any, Optional


class ApiError(Exception):
    """Raised anywhere; rendered as {"error": {"code", "message", **extra}}."""

    def __init__(self, status: int, code: str, message: str, extra: Optional[dict[str, Any]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra or {}

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


def validation(message: str) -> ApiError:
    return ApiError(422, "VALIDATION", message)


def not_found(message: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", message)
