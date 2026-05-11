"""Official Python SDK for the InCheck AI platform."""

from ._version import __version__
from .async_client import AsyncClient
from .client import Client
from .exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    IncheckError,
    JobFailedError,
    JobTimeoutError,
    NotFoundError,
    PermissionError,
    RateLimitError,
    ValidationError,
)
from .models import (
    ChatChunk,
    ChatResponse,
    DeleteResponse,
    DocumentInfo,
    DocumentListResponse,
    HealthResponse,
    JobProgress,
    JobStatus,
    OrgInfo,
    OrgListResponse,
    PresignedUpload,
    UpdateInitiated,
    UploadCompleted,
    UploadInitiated,
    VersionInfo,
)

__all__ = [
    "__version__",
    # clients
    "Client",
    "AsyncClient",
    # errors
    "IncheckError",
    "APIConnectionError",
    "APIError",
    "AuthenticationError",
    "JobFailedError",
    "JobTimeoutError",
    "NotFoundError",
    "PermissionError",
    "RateLimitError",
    "ValidationError",
    # models
    "ChatChunk",
    "ChatResponse",
    "DeleteResponse",
    "DocumentInfo",
    "DocumentListResponse",
    "HealthResponse",
    "JobProgress",
    "JobStatus",
    "OrgInfo",
    "OrgListResponse",
    "PresignedUpload",
    "UpdateInitiated",
    "UploadCompleted",
    "UploadInitiated",
    "VersionInfo",
]
