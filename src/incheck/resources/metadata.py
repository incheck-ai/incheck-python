"""Metadata — reference data the gateway exposes for UI / clients.

Right now this is a single endpoint: the canonical list of ``state``
and ``scope`` values that ``/chat`` accepts. The list lives server-side
and is editable without a client redeploy — fetch it at startup (or on
demand) instead of hard-coding values.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._transport import handle_response
from ..models import StatesAndScopesResponse

if TYPE_CHECKING:
    from ..async_client import AsyncClient
    from ..client import Client


class MetadataResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def states_and_scopes(self) -> StatesAndScopesResponse:
        """Fetch the canonical ``state`` / ``scope`` reference data.

        Returns a :class:`~incheck.models.StatesAndScopesResponse` with
        the default state and scope, the full enumerations, and a
        ``scopes_by_state`` map. Only the ``value`` field on each entry
        is accepted by ``/chat`` — ``label`` is for human display.

        Example:
            >>> meta = client.metadata.states_and_scopes()
            >>> reply = client.chat.send(
            ...     "Adult atropine dose for bradycardia?",
            ...     scope=meta.default_scope,
            ...     state=meta.default_state,
            ... )
        """
        response = self._client._http.get("/states-and-scopes")
        if response.status_code != 200:
            handle_response(response)  # raises
        return StatesAndScopesResponse.model_validate(response.json())


class AsyncMetadataResource:
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def states_and_scopes(self) -> StatesAndScopesResponse:
        """Async counterpart of :meth:`MetadataResource.states_and_scopes`."""
        response = await self._client._http.get("/states-and-scopes")
        if response.status_code != 200:
            handle_response(response)  # raises
        return StatesAndScopesResponse.model_validate(response.json())
