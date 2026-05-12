from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _IncheckModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class PresignedUpload(_IncheckModel):
    """One file's presigned-POST credentials, returned by ``initiate-upload``.

    Pass ``upload_fields`` verbatim as multipart form fields, then attach the
    file under the ``file`` field, and POST to ``upload_url``. S3 will respond
    with ``204 No Content`` on success.
    """

    filename: str
    upload_url: str
    upload_fields: dict[str, str]
    s3_key: str
    is_update: bool | None = None


class UploadInitiated(_IncheckModel):
    """Result of a successful ``documents.initiate_upload`` call."""

    job_id: str
    org_name: str
    org_id: str
    version: str
    s3_folder: str
    upload_urls: list[PresignedUpload]
    expires_in: int
    created_at: datetime


class UploadCompleted(_IncheckModel):
    """Result of ``documents.complete_upload`` — processing has been triggered."""

    job_id: str
    status: str
    org_name: str
    org_id: str
    version: str
    s3_folder: str
    files_confirmed: list[str]
    created_at: datetime


class UpdateInitiated(_IncheckModel):
    """Result of ``documents.initiate_update`` for an existing org_id."""

    job_id: str
    org_name: str
    org_id: str
    current_version: str | None = None
    new_version: str
    s3_folder: str
    upload_urls: list[PresignedUpload]
    existing_documents_to_keep: list[str]
    expires_in: int
    created_at: datetime


class OrgInfo(_IncheckModel):
    """A single org_id discovered under your namespace."""

    org_id: str
    org_name: str | None = None
    current_version: str | None = None
    document_count: int | None = None
    last_updated_at: datetime | None = None


class OrgListResponse(_IncheckModel):
    """Result of ``documents.list_orgs()`` — always filtered to your namespace."""

    org_ids: list[OrgInfo | str]
    total_count: int
    filtered_by: str


class DocumentInfo(_IncheckModel):
    """A single document inside an org_id's current version.

    ``download_url`` exposes the short-lived presigned GET URL (the API
    field name is ``presigned_url``; the SDK normalises to
    ``download_url`` for symmetry with other SDKs).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    filename: str
    s3_key: str | None = None
    size_bytes: int | None = None
    download_url: str | None = None
    url_expires_in: int | None = None
    last_modified: datetime | None = None

    def __init__(self, **data: Any) -> None:  # type: ignore[override]
        if "presigned_url" in data and "download_url" not in data:
            data["download_url"] = data.pop("presigned_url")
        super().__init__(**data)


class DocumentListResponse(_IncheckModel):
    org_id: str
    version: str | None = None
    job_id: str | None = None
    s3_folder: str | None = None
    document_count: int | None = None
    documents: list[DocumentInfo]
    expires_in: int | None = None


class VersionInfo(_IncheckModel):
    org_id: str
    current_version: str | None = None
    job_id: str | None = None
    s3_folder: str | None = None
    updated_at: datetime | None = None


class JobProgress(_IncheckModel):
    total_documents: int = 0
    total_pages: int = 0
    processed_pages: int = 0


class JobStatus(_IncheckModel):
    """Status of a document-processing job.

    ``status`` is one of: ``initiated``, ``pending``, ``processing``,
    ``completed``, ``failed``. Use :meth:`is_terminal` to check.
    """

    job_id: str
    status: str
    org_name: str | None = None
    org_id: str | None = None
    version: str | None = None
    s3_folder: str | None = None
    progress: JobProgress = JobProgress()
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")

    def is_successful(self) -> bool:
        return self.status == "completed"


class DeleteResponse(_IncheckModel):
    """Result of a successful delete.

    The API returns 2xx on a successful delete with a body shaped like
    ``{"message": "Deleted permanently"}``. ``success`` is synthesised
    from the HTTP status — anything reaching this model is a success.
    """

    success: bool = True
    org_id: str | None = None
    version: str | None = None
    message: str | None = None


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class ChatMessage(_IncheckModel):
    """One prior turn in a multi-turn chat.

    Wire-compatible with the OpenAI / Anthropic Messages API shape.
    Pass a list of these (or plain dicts of the same shape) as
    ``messages=`` to :meth:`incheck.Client.chat.send` / ``stream`` to
    give the model the conversation so far. Prior turns must alternate
    ``user`` / ``assistant`` starting with ``user`` and ending with
    ``assistant`` — the current user turn lives in the positional
    ``content`` argument and is appended by the gateway.
    """

    role: Literal["user", "assistant"]
    content: str


class ChatChunk(_IncheckModel):
    """A single Server-Sent-Event payload from streaming /chat.

    Streamed chunks carry ``content`` deltas. The final event has
    ``type='complete'`` and no ``content``.
    """

    content: str | None = None
    type: str | None = None
    error: str | None = None


class ChatResponse(_IncheckModel):
    """Aggregated non-streaming chat reply."""

    content: str
    raw: list[ChatChunk] | None = None


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


class HealthResponse(_IncheckModel):
    status: str
    extra: dict[str, Any] | None = None
