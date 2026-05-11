from __future__ import annotations

from typing import Any


class IncheckError(Exception):
    """Base class for all InCheck SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_body = response_body

    @property
    def detail(self) -> str:
        if isinstance(self.response_body, dict):
            value = self.response_body.get("detail")
            if isinstance(value, str):
                return value
        return self.message

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, "
            f"message={self.message!r})"
        )


class APIConnectionError(IncheckError):
    """Network-level failure reaching the gateway."""


class APIError(IncheckError):
    """5xx response from the gateway or an upstream service."""


class AuthenticationError(IncheckError):
    """401 — missing or invalid API key."""


class PermissionError(IncheckError):  # noqa: A001 - intentional shadow of builtin
    """403 — caller is authenticated but not allowed (often a namespace mismatch)."""


class NotFoundError(IncheckError):
    """404 — resource (org, job, version) does not exist."""


class ValidationError(IncheckError):
    """400 / 422 — request did not pass validation."""


class RateLimitError(IncheckError):
    """429 — per-key rate limit exceeded."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, response_body=response_body)
        self.retry_after = retry_after


class JobFailedError(IncheckError):
    """A document-processing job ended in a failed/error state."""

    def __init__(self, message: str, *, job_id: str, status: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.status = status


class JobTimeoutError(IncheckError):
    """``wait_for_job`` exceeded its deadline before the job reached a terminal state."""

    def __init__(self, message: str, *, job_id: str, last_status: str | None) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.last_status = last_status
