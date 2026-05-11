"""Document onboarding — proxies ``/documents/*`` on the InCheck gateway.

The flow is always: initiate → PUT to presigned S3 URLs → complete → poll.
The high-level :meth:`DocumentsResource.upload` helper does all four steps
in one call and returns the terminal :class:`~incheck.models.JobStatus`.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import IO, TYPE_CHECKING, Iterable, Sequence, Union

import httpx

from .._transport import handle_response
from ..exceptions import JobFailedError, JobTimeoutError, ValidationError
from ..models import (
    DeleteResponse,
    DocumentListResponse,
    JobStatus,
    OrgListResponse,
    PresignedUpload,
    UpdateInitiated,
    UploadCompleted,
    UploadInitiated,
    VersionInfo,
)

if TYPE_CHECKING:
    from ..async_client import AsyncClient
    from ..client import Client


PathLike = Union[str, os.PathLike[str], Path]
FileSpec = Union[PathLike, tuple[str, IO[bytes]]]


def _normalise_file(spec: FileSpec) -> tuple[str, IO[bytes] | bytes, bool]:
    """Return ``(filename, body, must_close)`` for an entry passed to ``upload``.

    Accepts:
      * a path-like (``str`` / ``pathlib.Path``) — opened here, closed by caller
      * a ``(filename, file_like)`` tuple — borrowed; caller owns lifecycle
    """
    if isinstance(spec, tuple):
        filename, body = spec
        return filename, body, False
    path = Path(os.fspath(spec))
    if not path.exists():
        raise ValidationError(f"File not found: {path}")
    return path.name, path.open("rb"), True


def _post_presigned(http: httpx.Client | httpx.AsyncClient, presigned: PresignedUpload,
                    body: IO[bytes] | bytes) -> httpx.Response:
    files = {"file": (presigned.filename, body)}
    return http.post(presigned.upload_url, data=presigned.upload_fields, files=files)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class DocumentsResource:
    def __init__(self, client: "Client") -> None:
        self._client = client

    # --- listing -----------------------------------------------------------

    def list_orgs(self) -> OrgListResponse:
        """Every org_id under your namespace."""
        response = self._client._http.get("/documents/orgs")
        return OrgListResponse.model_validate(handle_response(response))

    def list(self, org_id: str) -> DocumentListResponse:
        """All documents in an org_id's current version (with presigned GETs)."""
        response = self._client._http.get(f"/documents/orgs/{org_id}/documents")
        return DocumentListResponse.model_validate(handle_response(response))

    def version(self, org_id: str) -> VersionInfo:
        response = self._client._http.get(f"/documents/orgs/{org_id}/version")
        return VersionInfo.model_validate(handle_response(response))

    # --- creation / update -------------------------------------------------

    def initiate_upload(
        self,
        org_id: str,
        filenames: Sequence[str],
        *,
        batch_size: int = 6,
    ) -> UploadInitiated:
        body = {"org_id": org_id, "filenames": list(filenames), "batch_size": batch_size}
        response = self._client._http.post("/documents/initiate-upload", json=body)
        return UploadInitiated.model_validate(handle_response(response))

    def complete_upload(self, job_id: str, uploaded_files: Sequence[str]) -> UploadCompleted:
        body = {"job_id": job_id, "uploaded_files": list(uploaded_files)}
        response = self._client._http.post("/documents/complete-upload", json=body)
        return UploadCompleted.model_validate(handle_response(response))

    def initiate_update(
        self,
        org_id: str,
        filenames: Sequence[str],
        *,
        batch_size: int = 6,
    ) -> UpdateInitiated:
        body = {"filenames": list(filenames), "batch_size": batch_size}
        response = self._client._http.put(
            f"/documents/orgs/{org_id}/documents/initiate", json=body
        )
        return UpdateInitiated.model_validate(handle_response(response))

    def complete_update(
        self, org_id: str, job_id: str, uploaded_files: Sequence[str]
    ) -> UploadCompleted:
        body = {"job_id": job_id, "uploaded_files": list(uploaded_files)}
        response = self._client._http.put(
            f"/documents/orgs/{org_id}/documents/complete", json=body
        )
        return UploadCompleted.model_validate(handle_response(response))

    # --- jobs --------------------------------------------------------------

    def job(self, job_id: str) -> JobStatus:
        response = self._client._http.get(f"/documents/job/{job_id}")
        return JobStatus.model_validate(handle_response(response))

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 600.0,
        poll_interval: float = 10.0,
    ) -> JobStatus:
        """Block until the job reaches a terminal state or ``timeout`` elapses.

        Raises :class:`~incheck.exceptions.JobFailedError` on ``failed`` and
        :class:`~incheck.exceptions.JobTimeoutError` if the deadline is hit.
        """
        deadline = time.monotonic() + timeout
        last: JobStatus | None = None
        while True:
            last = self.job(job_id)
            if last.is_terminal():
                if not last.is_successful():
                    raise JobFailedError(
                        last.error or f"job {job_id} ended with status {last.status}",
                        job_id=job_id,
                        status=last.status,
                    )
                return last
            if time.monotonic() >= deadline:
                raise JobTimeoutError(
                    f"job {job_id} did not complete within {timeout:.0f}s",
                    job_id=job_id,
                    last_status=last.status if last else None,
                )
            time.sleep(poll_interval)

    # --- deletion ----------------------------------------------------------

    def delete_version(self, org_id: str, version: str) -> DeleteResponse:
        response = self._client._http.delete(
            f"/documents/orgs/{org_id}/versions/{version}"
        )
        return DeleteResponse.model_validate(handle_response(response))

    def delete(self, org_id: str) -> DeleteResponse:
        response = self._client._http.delete(f"/documents/orgs/{org_id}")
        return DeleteResponse.model_validate(handle_response(response))

    # --- convenience -------------------------------------------------------

    def upload(
        self,
        org_id: str,
        files: Iterable[FileSpec],
        *,
        batch_size: int = 6,
        wait: bool = True,
        timeout: float = 600.0,
        poll_interval: float = 10.0,
    ) -> JobStatus | UploadCompleted:
        """Initiate → PUT to S3 → complete → (optionally) poll until done.

        Args:
            org_id: Hierarchical org_id (must start with your namespace).
            files: Local paths or ``(filename, file_like)`` tuples.
            batch_size: Document-chunking batch size (1-20).
            wait: When True (default), block until the processing job
                reaches a terminal state and return the final :class:`JobStatus`.
                When False, return the :class:`UploadCompleted` from
                ``complete-upload`` and let the caller poll.
            timeout: Max seconds to wait when ``wait=True``.
            poll_interval: Seconds between status polls.
        """
        specs = list(files)
        if not specs:
            raise ValidationError("files cannot be empty")

        opened: list[tuple[str, IO[bytes] | bytes, bool]] = []
        try:
            for spec in specs:
                opened.append(_normalise_file(spec))
            filenames = [name for name, _body, _close in opened]

            initiated = self.initiate_upload(org_id, filenames, batch_size=batch_size)
            url_by_name = {u.filename: u for u in initiated.upload_urls}

            with httpx.Client(timeout=self._client._http.timeout) as s3:
                for name, body, _close in opened:
                    presigned = url_by_name.get(name)
                    if presigned is None:
                        raise ValidationError(
                            f"Gateway did not return a presigned upload for {name!r}"
                        )
                    if hasattr(body, "seek"):
                        try:
                            body.seek(0)  # type: ignore[union-attr]
                        except Exception:
                            pass
                    resp = _post_presigned(s3, presigned, body)
                    if resp.status_code not in (200, 204):
                        raise ValidationError(
                            f"S3 upload failed for {name!r}: "
                            f"HTTP {resp.status_code} {resp.text[:200]}"
                        )

            completed = self.complete_upload(initiated.job_id, filenames)
            if not wait:
                return completed
            return self.wait_for_job(
                completed.job_id, timeout=timeout, poll_interval=poll_interval
            )
        finally:
            for _name, body, must_close in opened:
                if must_close and hasattr(body, "close"):
                    try:
                        body.close()  # type: ignore[union-attr]
                    except Exception:
                        pass


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class AsyncDocumentsResource:
    def __init__(self, client: "AsyncClient") -> None:
        self._client = client

    async def list_orgs(self) -> OrgListResponse:
        response = await self._client._http.get("/documents/orgs")
        return OrgListResponse.model_validate(handle_response(response))

    async def list(self, org_id: str) -> DocumentListResponse:
        response = await self._client._http.get(f"/documents/orgs/{org_id}/documents")
        return DocumentListResponse.model_validate(handle_response(response))

    async def version(self, org_id: str) -> VersionInfo:
        response = await self._client._http.get(f"/documents/orgs/{org_id}/version")
        return VersionInfo.model_validate(handle_response(response))

    async def initiate_upload(
        self,
        org_id: str,
        filenames: Sequence[str],
        *,
        batch_size: int = 6,
    ) -> UploadInitiated:
        body = {"org_id": org_id, "filenames": list(filenames), "batch_size": batch_size}
        response = await self._client._http.post("/documents/initiate-upload", json=body)
        return UploadInitiated.model_validate(handle_response(response))

    async def complete_upload(self, job_id: str, uploaded_files: Sequence[str]) -> UploadCompleted:
        body = {"job_id": job_id, "uploaded_files": list(uploaded_files)}
        response = await self._client._http.post("/documents/complete-upload", json=body)
        return UploadCompleted.model_validate(handle_response(response))

    async def initiate_update(
        self,
        org_id: str,
        filenames: Sequence[str],
        *,
        batch_size: int = 6,
    ) -> UpdateInitiated:
        body = {"filenames": list(filenames), "batch_size": batch_size}
        response = await self._client._http.put(
            f"/documents/orgs/{org_id}/documents/initiate", json=body
        )
        return UpdateInitiated.model_validate(handle_response(response))

    async def complete_update(
        self, org_id: str, job_id: str, uploaded_files: Sequence[str]
    ) -> UploadCompleted:
        body = {"job_id": job_id, "uploaded_files": list(uploaded_files)}
        response = await self._client._http.put(
            f"/documents/orgs/{org_id}/documents/complete", json=body
        )
        return UploadCompleted.model_validate(handle_response(response))

    async def job(self, job_id: str) -> JobStatus:
        response = await self._client._http.get(f"/documents/job/{job_id}")
        return JobStatus.model_validate(handle_response(response))

    async def wait_for_job(
        self,
        job_id: str,
        *,
        timeout: float = 600.0,
        poll_interval: float = 10.0,
    ) -> JobStatus:
        deadline = asyncio.get_event_loop().time() + timeout
        last: JobStatus | None = None
        while True:
            last = await self.job(job_id)
            if last.is_terminal():
                if not last.is_successful():
                    raise JobFailedError(
                        last.error or f"job {job_id} ended with status {last.status}",
                        job_id=job_id,
                        status=last.status,
                    )
                return last
            if asyncio.get_event_loop().time() >= deadline:
                raise JobTimeoutError(
                    f"job {job_id} did not complete within {timeout:.0f}s",
                    job_id=job_id,
                    last_status=last.status if last else None,
                )
            await asyncio.sleep(poll_interval)

    async def delete_version(self, org_id: str, version: str) -> DeleteResponse:
        response = await self._client._http.delete(
            f"/documents/orgs/{org_id}/versions/{version}"
        )
        return DeleteResponse.model_validate(handle_response(response))

    async def delete(self, org_id: str) -> DeleteResponse:
        response = await self._client._http.delete(f"/documents/orgs/{org_id}")
        return DeleteResponse.model_validate(handle_response(response))

    async def upload(
        self,
        org_id: str,
        files: Iterable[FileSpec],
        *,
        batch_size: int = 6,
        wait: bool = True,
        timeout: float = 600.0,
        poll_interval: float = 10.0,
    ) -> JobStatus | UploadCompleted:
        specs = list(files)
        if not specs:
            raise ValidationError("files cannot be empty")

        opened: list[tuple[str, IO[bytes] | bytes, bool]] = []
        try:
            for spec in specs:
                opened.append(_normalise_file(spec))
            filenames = [name for name, _body, _close in opened]

            initiated = await self.initiate_upload(org_id, filenames, batch_size=batch_size)
            url_by_name = {u.filename: u for u in initiated.upload_urls}

            async with httpx.AsyncClient(timeout=self._client._http.timeout) as s3:
                for name, body, _close in opened:
                    presigned = url_by_name.get(name)
                    if presigned is None:
                        raise ValidationError(
                            f"Gateway did not return a presigned upload for {name!r}"
                        )
                    if hasattr(body, "seek"):
                        try:
                            body.seek(0)  # type: ignore[union-attr]
                        except Exception:
                            pass
                    files_payload = {"file": (presigned.filename, body)}
                    resp = await s3.post(
                        presigned.upload_url,
                        data=presigned.upload_fields,
                        files=files_payload,
                    )
                    if resp.status_code not in (200, 204):
                        raise ValidationError(
                            f"S3 upload failed for {name!r}: "
                            f"HTTP {resp.status_code} {resp.text[:200]}"
                        )

            completed = await self.complete_upload(initiated.job_id, filenames)
            if not wait:
                return completed
            return await self.wait_for_job(
                completed.job_id, timeout=timeout, poll_interval=poll_interval
            )
        finally:
            for _name, body, must_close in opened:
                if must_close and hasattr(body, "close"):
                    try:
                        body.close()  # type: ignore[union-attr]
                    except Exception:
                        pass
