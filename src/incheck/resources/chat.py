"""Chat — proxies ``/chat`` on the InCheck gateway.

InCheck has two operating modes, both served by the same call:

**EMS mode** — answers from general EMS knowledge under the given
``scope`` and ``state``. No document retrieval. Use it when you don't
have a knowledge Pod onboarded yet, or for questions that aren't tied
to a specific document.

**Unified mode** — answers grounded in the documents you've onboarded
into a Pod (one Pod per ``org_id``). Pass ``org_id`` to enable it;
omit ``org_id`` for EMS mode. ``org_id`` may be a single id (one Pod)
**or a list of ids** to fan retrieval across multiple Pods in one
request.

Carry **multi-turn context** by passing prior turns as ``messages=`` —
the same shape used by the OpenAI / Anthropic Messages API. The
current user turn stays in the positional ``content`` argument; the
gateway appends it before forwarding upstream.

You can supply ``send`` for a single aggregated reply or ``stream`` for
incremental :class:`~incheck.models.ChatChunk` events.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, AsyncIterator, Iterator, Sequence, Union

from ..exceptions import IncheckError
from ..models import ChatChunk, ChatMessage, ChatResponse

if TYPE_CHECKING:
    from ..async_client import AsyncClient
    from ..client import Client


# Public type aliases. Mirror the gateway's ``CustomerChatRequest`` shape:
# ``org_id`` may be a scalar or a list; ``messages`` accepts both
# ``ChatMessage`` instances and plain dicts for ergonomic call sites.
OrgIdOrList = Union[str, list[str]]
MessageInput = Union[ChatMessage, dict]


def _normalise_messages(messages: Sequence[MessageInput] | None) -> list[dict] | None:
    """Coerce ``messages`` to the JSON shape the gateway expects.

    Accepts a list mixing ``ChatMessage`` instances and plain dicts so
    customers can use whichever they already have lying around. Returns
    ``None`` when there are no prior turns to send.
    """
    if not messages:
        return None
    out: list[dict] = []
    for m in messages:
        if isinstance(m, ChatMessage):
            out.append(m.model_dump())
        elif isinstance(m, dict):
            # Trust the gateway's validator for shape — but normalise
            # away anything that obviously doesn't belong on the wire.
            out.append({"role": m["role"], "content": m["content"]})
        else:
            raise TypeError(
                "messages entries must be ChatMessage or dict with "
                f"'role' and 'content'; got {type(m).__name__}"
            )
    return out


def _build_payload(
    *,
    content: str,
    user_id: str,
    conversation_id: str | None,
    scope: str,
    state: str,
    streaming: bool,
    conversation_hx: str | None,
    org_id: OrgIdOrList | None,
    messages: Sequence[MessageInput] | None,
) -> dict:
    payload: dict = {
        "conversation_id": conversation_id or str(uuid.uuid4()),
        "user_id": user_id,
        "streaming": streaming,
        "content": content,
        "scope": scope,
        "state": state,
    }
    # ``conversation_hx`` is the legacy single-string history field.
    # ``messages`` is the new standard shape. The gateway rejects both
    # at once (422). Only forward whichever the caller actually set.
    normalised = _normalise_messages(messages)
    if normalised is not None:
        payload["messages"] = normalised
    elif conversation_hx is not None:
        payload["conversation_hx"] = conversation_hx
    # Unified mode is opt-in. Omitting the key — not setting it to null —
    # keeps the gateway log clean and avoids any chance of a flaky upstream
    # treating null differently from missing. An empty list also routes
    # to EMS mode, so we drop it before sending.
    if org_id:
        if isinstance(org_id, list) and not org_id:
            pass
        else:
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
        org_id: OrgIdOrList | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        messages: Sequence[MessageInput] | None = None,
        conversation_hx: str | None = None,
    ) -> ChatResponse:
        """Send a chat message and return the aggregated reply.

        Args:
            content: The current user message.
            org_id: Optional. Pass your Pod's hierarchical org_id to run
                in **unified mode** (retrieval-aware against the documents
                onboarded into that Pod via the Documents API). Pass a
                **list** of org_ids to fan retrieval across several Pods
                in one request. Omit it to run in **EMS mode** (general
                EMS knowledge, no retrieval). Every id's first segment
                must equal your namespace.
            user_id: An identifier for the end-user. Audit trail only.
            conversation_id: Optional — a UUID is generated if omitted.
            scope: EMS scope (``"ALS"``, ``"BLS"``, …).
            state: US state for state-specific protocols.
            messages: Optional prior turns as ``ChatMessage`` instances
                or plain ``{"role", "content"}`` dicts. Must alternate
                ``user`` / ``assistant`` starting with ``user`` and
                ending with ``assistant`` — the current user turn
                stays in ``content`` and is appended by the gateway.
                Works in both EMS and unified mode.
            conversation_hx: Deprecated. Prefer ``messages``. The
                legacy single-string history field, still accepted by
                the gateway in EMS mode for back-compat. Mutually
                exclusive with ``messages`` — the gateway returns 422
                if both are set.

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

            >>> # Multi-Pod fan-out — retrieve from both Pods in one call
            >>> client.chat.send(
            ...     "Compare hazmat escalation between dispatch and wilderness ops.",
            ...     org_id=["acme_dispatch", "acme_wilderness"],
            ... )

            >>> # Multi-turn — pass prior turns as messages
            >>> from incheck import ChatMessage
            >>> client.chat.send(
            ...     "And for a 6-year-old?",
            ...     messages=[
            ...         ChatMessage(role="user", content="Adult atropine dose?"),
            ...         ChatMessage(role="assistant", content="1 mg IV/IO q3-5min, max 3 mg."),
            ...     ],
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
            messages=messages,
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
        org_id: OrgIdOrList | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        messages: Sequence[MessageInput] | None = None,
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
            messages=messages,
        )
        with self._client._http.stream("POST", "/chat", json=payload) as response:
            if response.status_code != 200:
                # `handle_response` inspects the body — on a streamed
                # response that hasn't been read yet, touching `.content`
                # raises ``ResponseNotRead``. Read the (typically tiny)
                # error body first so the typed exception carries the
                # actual server detail.
                response.read()
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
        org_id: OrgIdOrList | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        messages: Sequence[MessageInput] | None = None,
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
            messages=messages,
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
        org_id: OrgIdOrList | None = None,
        user_id: str = "sdk",
        conversation_id: str | None = None,
        scope: str = "ALS",
        state: str = "Massachusetts",
        messages: Sequence[MessageInput] | None = None,
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
            messages=messages,
        )
        async with self._client._http.stream("POST", "/chat", json=payload) as response:
            if response.status_code != 200:
                # See sync `stream` — must read the body before
                # ``handle_response`` can inspect it.
                await response.aread()
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
