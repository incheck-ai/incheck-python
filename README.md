# incheck

The official Python SDK for the [InCheck AI](https://incheck.ai) platform.
Onboard documents into per-tenant collections and chat against them with
typed, retrieval-aware responses — in a few lines of idiomatic Python.

> **Status:** `0.0.1` — document onboarding + chat (sync + async + streaming).
> Default is **production** (`https://api.incheck.ai`). Use the **staging**
> environment (`https://api-acceptance.incheck.ai`) to validate your
> integration end-to-end before going live.

## Install

```bash
pip install incheck
# or
uv add incheck
```

Requires Python 3.10+.

## Authenticate

Generate an API key from the InCheck admin (`/admin/api-keys` — Teams plan
+ admin role required) and either pass it explicitly or set the env var:

```bash
export INCHECK_API_KEY="incheck_prod_..."
```

The SDK never sends your org UUID on the wire — the gateway derives it
from your key and enforces a per-tenant **namespace** on every request.
Your namespace is the lowercase-alphanumeric form of your subdomain, and
every `org_id` you push to or chat against must start with `<namespace>_`.

## Quickstart

```python
from incheck import Client

with Client() as client:
    namespace = client.documents.list_orgs().filtered_by
    org_id = f"{namespace}_dispatch"

    # Upload — initiate → S3 (presigned) → complete → poll, all in one call
    status = client.documents.upload(
        org_id,
        files=["./protocols.pdf", "./policies.docx"],
    )
    print("processed:", status.progress.processed_pages, "pages")

    # Chat — retrieval-aware against the ingested corpus
    reply = client.chat.send(
        org_id,
        "What are the indications for epinephrine in our protocols?",
        user_id="alice@hospital.org",
    )
    print(reply.content)
```

## Streaming

```python
for chunk in client.chat.stream(org_id, "Summarize the dispatch SOP."):
    if chunk.content:
        print(chunk.content, end="", flush=True)
```

## Async

The SDK ships an async client that mirrors the sync API one-for-one:

```python
import asyncio
from incheck import AsyncClient

async def main():
    async with AsyncClient() as client:
        status = await client.documents.upload("acme_dispatch", ["./doc.pdf"])
        reply = await client.chat.send("acme_dispatch", "Summarize.")
        print(reply.content)

asyncio.run(main())
```

## Endpoints covered in 0.0.1

### Documents

| Method | Description |
|---|---|
| `client.documents.list_orgs()` | every org_id under your namespace |
| `client.documents.list(org_id)` | documents in the current version, with presigned GETs |
| `client.documents.version(org_id)` | metadata about the current version |
| `client.documents.upload(org_id, files, wait=True)` | one-shot initiate → S3 → complete → wait |
| `client.documents.initiate_upload(...)` | low-level — get presigned POSTs |
| `client.documents.complete_upload(...)` | low-level — trigger processing |
| `client.documents.initiate_update(...)` | add/replace files in an existing org_id |
| `client.documents.complete_update(...)` | finalise an update |
| `client.documents.job(job_id)` | status snapshot |
| `client.documents.wait_for_job(job_id)` | block until the job is terminal |
| `client.documents.delete_version(org_id, version)` | delete one version |
| `client.documents.delete(org_id)` | delete the entire org_id |

### Chat

| Method | Description |
|---|---|
| `client.chat.send(org_id, content, ...)` | full reply, retrieval-aware |
| `client.chat.stream(org_id, content, ...)` | yields chunks as they arrive (SSE) |

`AsyncClient` exposes the same methods under the same names.

## Errors

Every non-2xx response becomes a typed exception:

```python
from incheck import (
    Client,
    AuthenticationError,
    PermissionError,
    JobFailedError,
    JobTimeoutError,
    RateLimitError,
)

with Client() as client:
    try:
        client.documents.upload("royal_dispatch", ["./doc.pdf"])  # wrong namespace
    except PermissionError as e:
        print("nope:", e)              # 403 from the gateway namespace check
    except JobFailedError as e:
        print("processing failed:", e.status)
    except JobTimeoutError as e:
        print("still pending:", e.last_status)
    except RateLimitError as e:
        print(f"slow down; retry after {e.retry_after}s")
    except AuthenticationError:
        print("check your API key")
```

Hierarchy: `IncheckError` → `AuthenticationError`, `PermissionError`,
`NotFoundError`, `ValidationError`, `RateLimitError`, `APIError`,
`APIConnectionError`, `JobFailedError`, `JobTimeoutError`.

## Environments

There are two managed environments. Production is the default; use staging
to validate your integration end-to-end before flipping over.

| Environment | Base URL | When to use |
|---|---|---|
| `production` | `https://api.incheck.ai` | live customer traffic |
| `staging` | `https://api-acceptance.incheck.ai` | integration testing, smoke flows |

Pick one in code or via env var (in priority order):

```python
# Explicit base URL — wins over everything
Client(base_url="https://api-acceptance.incheck.ai")

# Named environment
Client(environment="staging")

# From the env
# INCHECK_BASE_URL=...   or   INCHECK_ENVIRONMENT=staging
Client()
```

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `INCHECK_API_KEY` | — | required |
| `INCHECK_ENVIRONMENT` | `production` | `production` or `staging` |
| `INCHECK_BASE_URL` | — | full URL override (highest priority) |

You can also pass `api_key=`, `environment=`, and `base_url=` explicitly.

## License

MIT.
