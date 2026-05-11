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
