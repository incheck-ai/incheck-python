"""Document-aware chat — proxies ``/chat`` on the InCheck gateway.

The gateway always streams internally; the SDK exposes both modes:

* :meth:`ChatResource.send` returns a single :class:`ChatResponse` with the
  full content joined.
* :meth:`ChatResource.stream` yields :class:`ChatChunk` events as they arrive.

The ``org_id`` you pass MUST be hierarchical and start with your namespace
(the same value you use when onboarding documents). It drives unified-mode
retrieval upstream — chat answers will reference your ingested corpus.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, AsyncIterator, Iterator

from ..exceptions import IncheckError
from ..models import ChatChunk, ChatResponse

if TYPE_CHECKING:
    from ..async_client import AsyncClient
    from ..client import Client


def _build_payload(
    *,
    org_id: str,
    content: str,
    user_id: str,
    conversation_id: str | None,
    scope: str,
    state: str,
    streaming: bool,
    conversation_hx: str | None,
) -> dict:
    return {
        "conversation_id": conversation_id or str(uuid.uuid4()),
        "user_id": user_id,
        "org_id": org_id,
        "streaming": streaming,
        "content": content,
        "scope": scope,
        "state": state,
        "conversation_hx": conversation_hx,
    }


def _iter_sse_lines(text: str) -> Iterator[ChatChunk]:
    for raw in text.splitlines():
        line = raw.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        yield ChatChunk.model_validate(data)


def _aggregate(chunks: list[ChatChunk]) -> ChatResponse:
    pieces: list[str] = []
    for c in chunks:
        if c.error:
            raise IncheckError(f"chat error: {c.error}")
        if c.content:
            pieces.append(c.content)
    return ChatResponse(content="".join(pieces), raw=chunks)


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class ChatResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def send(
        self,
        org_id: str,
        content: str,
        *,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> ChatResponse:
        """Send a chat message and return the aggregated reply.

        Args:
            org_id: Your hierarchical org_id (e.g. ``"acme_dispatch"``).
            content: The user message.
            user_id: An identifier for the end-user. Free-form.
            conversation_id: Optional — a UUID is generated if omitted.
            scope: EMS scope (``"ALS"``, ``"BLS"``, …).
            state: US state for state-specific protocols.
            conversation_hx: Optional prior conversation context.
        """
        payload = _build_payload(
            org_id=org_id,
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=False,
            conversation_hx=conversation_hx,
        )
        response = self._client._http.post("/chat", json=payload)
        if response.status_code != 200:
            from .._transport import handle_response

            handle_response(response)  # raises
        chunks = list(_iter_sse_lines(response.text))
        return _aggregate(chunks)

    def stream(
        self,
        org_id: str,
        content: str,
        *,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> Iterator[ChatChunk]:
        """Stream chat chunks as they arrive (SSE).

        The generator terminates on the ``type='complete'`` marker.
        """
        payload = _build_payload(
            org_id=org_id,
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=True,
            conversation_hx=conversation_hx,
        )
        with self._client._http.stream("POST", "/chat", json=payload) as response:
            if response.status_code != 200:
                from .._transport import handle_response

                handle_response(response)  # raises
            for line in response.iter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                chunk = ChatChunk.model_validate(data)
                if chunk.error:
                    raise IncheckError(f"chat error: {chunk.error}")
                yield chunk
                if chunk.type == "complete":
                    return


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class AsyncChatResource:
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def send(
        self,
        org_id: str,
        content: str,
        *,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> ChatResponse:
        payload = _build_payload(
            org_id=org_id,
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=False,
            conversation_hx=conversation_hx,
        )
        response = await self._client._http.post("/chat", json=payload)
        if response.status_code != 200:
            from .._transport import handle_response

            handle_response(response)
        chunks = list(_iter_sse_lines(response.text))
        return _aggregate(chunks)

    async def stream(
        self,
        org_id: str,
        content: str,
        *,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        payload = _build_payload(
            org_id=org_id,
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=True,
            conversation_hx=conversation_hx,
        )
        async with self._client._http.stream("POST", "/chat", json=payload) as response:
            if response.status_code != 200:
                from .._transport import handle_response

                handle_response(response)
            async for line in response.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                raw = line[len("data:"):].strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                chunk = ChatChunk.model_validate(data)
                if chunk.error:
                    raise IncheckError(f"chat error: {chunk.error}")
                yield chunk
                if chunk.type == "complete":
                    return
