from __future__ import annotations

import os
from typing import Any

import httpx

from ._transport import DEFAULT_BASE_URL, build_headers
from .exceptions import AuthenticationError
from .resources import ChatResource, DocumentsResource


class Client:
    """Synchronous InCheck API client.

    Example:
        from incheck import Client

        with Client() as client:  # INCHECK_API_KEY from env
            for org in client.documents.list_orgs().org_ids:
                print(org)
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("INCHECK_API_KEY")
        if not resolved_key:
            raise AuthenticationError(
                "No API key provided. Pass api_key= or set INCHECK_API_KEY "
                "in the environment."
            )
        self._api_key = resolved_key
        resolved_base = os.environ.get("INCHECK_BASE_URL") or base_url
        self._base_url = resolved_base.rstrip("/")

        if http_client is not None:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = httpx.Client(
                base_url=self._base_url,
                headers=build_headers(resolved_key),
                timeout=timeout,
            )
            self._owns_http = True

        self.documents = DocumentsResource(self)
        self.chat = ChatResource(self)

    @property
    def base_url(self) -> str:
        return self._base_url

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
