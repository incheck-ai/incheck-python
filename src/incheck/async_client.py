from __future__ import annotations

import os
from typing import Any, Literal

import httpx

from ._transport import build_headers, resolve_base_url
from .exceptions import AuthenticationError
from .resources import AsyncChatResource, AsyncDocumentsResource


Environment = Literal["production", "staging"]


class AsyncClient:
    """Asynchronous InCheck API client.

    Example:
        import asyncio
        from incheck import AsyncClient

        async def main():
            async with AsyncClient(environment="staging") as client:
                orgs = await client.documents.list_orgs()
                print(orgs.org_ids)

        asyncio.run(main())
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        environment: Environment | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("INCHECK_API_KEY")
        if not resolved_key:
            raise AuthenticationError(
                "No API key provided. Pass api_key= or set INCHECK_API_KEY "
                "in the environment."
            )
        self._api_key = resolved_key
        self._base_url = resolve_base_url(
            explicit_base_url=base_url,
            environment=environment,
            env_base_url=os.environ.get("INCHECK_BASE_URL"),
            env_environment=os.environ.get("INCHECK_ENVIRONMENT"),
        ).rstrip("/")

        if http_client is not None:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers=build_headers(resolved_key),
                timeout=timeout,
            )
            self._owns_http = True

        self.documents = AsyncDocumentsResource(self)
        self.chat = AsyncChatResource(self)

    @property
    def base_url(self) -> str:
        return self._base_url

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()
