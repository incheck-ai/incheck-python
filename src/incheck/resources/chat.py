"""Chat — proxies ``/chat`` on the InCheck gateway.

InCheck has two operating modes, both served by the same call:

**EMS mode** — answers from general EMS knowledge under the given
``scope`` and ``state``. No document retrieval. Use it when you don't
have a knowledge Pod onboarded yet, or for questions that aren't tied
to a specific document.

**Unified mode** — answers grounded in the documents you've onboarded
into a Pod (one Pod per ``org_id``). Pass ``org_id`` to enable it;
omit ``org_id`` for EMS mode.

You can supply ``send`` for a single aggregated reply or ``stream`` for
incremental :class:`~incheck.models.ChatChunk` events.
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
    content: str,
    user_id: str,
    conversation_id: str | None,
    scope: str,
    state: str,
    streaming: bool,
    conversation_hx: str | None,
    org_id: str | None,
) -> dict:
    payload: dict = {
        "conversation_id": conversation_id or str(uuid.uuid4()),
        "user_id": user_id,
        "streaming": streaming,
        "content": content,
        "scope": scope,
        "state": state,
        "conversation_hx": conversation_hx,
    }
    # Unified mode is opt-in. Omitting the key — not setting it to null —
    # keeps the gateway log clean and avoids any chance of a flaky upstream
    # treating null differently from missing.
    if org_id:
        payload["org_id"] = org_id
    return payload


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
        content: str,
        *,
        org_id: str | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> ChatResponse:
        """Send a chat message and return the aggregated reply.

        Args:
            content: The user message.
            org_id: Optional. Pass your Pod's hierarchical org_id to run
                in **unified mode** (retrieval-aware against the documents
                onboarded into that Pod via the Documents API). Omit it
                to run in **EMS mode** (general EMS knowledge, no
                retrieval). First segment must equal your namespace.
            user_id: An identifier for the end-user. Audit trail only.
            conversation_id: Optional — a UUID is generated if omitted.
            scope: EMS scope (``"ALS"``, ``"BLS"``, …).
            state: US state for state-specific protocols.
            conversation_hx: Optional prior conversation context.

        Returns:
            A :class:`~incheck.models.ChatResponse` with ``content``
            joined and the raw chunks available on ``raw``.

        Example:
            >>> # EMS mode — no Pod needed
            >>> client.chat.send("Adult atropine dose for bradycardia?")

            >>> # Unified mode — answer from your onboarded Pod
            >>> client.chat.send(
            ...     "Per our SOP, what's the hazmat escalation path?",
            ...     org_id="acme_dispatch",
            ... )
        """
        payload = _build_payload(
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=False,
            conversation_hx=conversation_hx,
            org_id=org_id,
        )
        response = self._client._http.post("/chat", json=payload)
        if response.status_code != 200:
            from .._transport import handle_response

            handle_response(response)  # raises
        chunks = list(_iter_sse_lines(response.text))
        return _aggregate(chunks)

    def stream(
        self,
        content: str,
        *,
        org_id: str | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> Iterator[ChatChunk]:
        """Stream chat chunks as they arrive (SSE).

        Identical contract to :meth:`send`, but yields each
        :class:`~incheck.models.ChatChunk` as it lands. Terminates on
        the ``type='complete'`` marker.

        Example:
            >>> for chunk in client.chat.stream(
            ...     "Summarize the dispatch SOP.",
            ...     org_id="acme_dispatch",
            ... ):
            ...     if chunk.content:
            ...         print(chunk.content, end="", flush=True)
        """
        payload = _build_payload(
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=True,
            conversation_hx=conversation_hx,
            org_id=org_id,
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
        content: str,
        *,
        org_id: str | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> ChatResponse:
        """Async counterpart of :meth:`ChatResource.send`."""
        payload = _build_payload(
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=False,
            conversation_hx=conversation_hx,
            org_id=org_id,
        )
        response = await self._client._http.post("/chat", json=payload)
        if response.status_code != 200:
            from .._transport import handle_response

            handle_response(response)
        chunks = list(_iter_sse_lines(response.text))
        return _aggregate(chunks)

    async def stream(
        self,
        content: str,
        *,
        org_id: str | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        conversation_hx: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        """Async counterpart of :meth:`ChatResource.stream`."""
        payload = _build_payload(
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            scope=scope,
            state=state,
            streaming=True,
            conversation_hx=conversation_hx,
            org_id=org_id,
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
