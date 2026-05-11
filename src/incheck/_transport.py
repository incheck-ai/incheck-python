from __future__ import annotations

import json
from typing import Any

import httpx

from ._version import __version__
from .exceptions import (
    APIError,
    AuthenticationError,
    IncheckError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    ValidationError,
)

DEFAULT_BASE_URL = "https://api.incheck.ai"
USER_AGENT = f"incheck-python/{__version__}"

ENVIRONMENTS: dict[str, str] = {
    "production": "https://api.incheck.ai",
    "staging": "https://api-acceptance.incheck.ai",
}


def resolve_base_url(
    *,
    explicit_base_url: str | None,
    environment: str | None,
    env_base_url: str | None,
    env_environment: str | None,
) -> str:
    """Decide which base URL to use, in priority order.

    1. ``base_url=`` passed to the client constructor
    2. ``INCHECK_BASE_URL`` env var
    3. ``environment=`` passed to the constructor (``"production"`` / ``"staging"``)
    4. ``INCHECK_ENVIRONMENT`` env var
    5. Default production URL
    """
    if explicit_base_url:
        return explicit_base_url
    if env_base_url:
        return env_base_url
    env_name = (environment or env_environment or "").lower().strip()
    if env_name:
        if env_name not in ENVIRONMENTS:
            valid = ", ".join(sorted(ENVIRONMENTS))
            raise ValueError(
                f"Unknown environment {env_name!r}. Valid options: {valid}."
            )
        return ENVIRONMENTS[env_name]
    return DEFAULT_BASE_URL


def build_headers(api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if extra:
        headers.update(extra)
    return headers


def _parse_body(response: httpx.Response) -> Any:
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type and response.content:
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError):
            return response.text
    return response.text or None


def _extract_message(body: Any, fallback: str) -> str:
    if isinstance(body, dict):
        detail = body.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, list) and detail:
            return "; ".join(str(item) for item in detail)
    return fallback


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def handle_response(response: httpx.Response) -> Any:
    """Parse a successful response body or raise a typed exception."""
    if 200 <= response.status_code < 300:
        if not response.content:
            return None
        return _parse_body(response)

    body = _parse_body(response)
    status = response.status_code
    fallback = f"HTTP {status} from InCheck API"
    message = _extract_message(body, fallback)

    if status == 401:
        raise AuthenticationError(message, status_code=status, response_body=body)
    if status == 403:
        raise PermissionError(message, status_code=status, response_body=body)
    if status == 404:
        raise NotFoundError(message, status_code=status, response_body=body)
    if status == 429:
        raise RateLimitError(
            message,
            status_code=status,
            response_body=body,
            retry_after=_retry_after_seconds(response),
        )
    if status in (400, 422):
        raise ValidationError(message, status_code=status, response_body=body)
    if status >= 500:
        raise APIError(message, status_code=status, response_body=body)
    raise IncheckError(message, status_code=status, response_body=body)
