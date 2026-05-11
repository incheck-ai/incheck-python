# incheck

The official Python SDK for the [InCheck AI](https://incheck.ai) platform.
Two operating modes, one client, typed end-to-end:

- **EMS mode** — ask the model an EMS protocol question. No setup
  required beyond an API key.
- **Unified mode** — onboard one or more documents into a **Pod** (one
  Pod per `org_id`), then chat against that Pod and the answers are
  grounded in *your* content.

> **Status:** `0.0.2` — chat (EMS + unified, sync/async/streaming) and
> document onboarding (Pods, presigned uploads, processing jobs).

## Install

```bash
pip install incheck
# or
uv add incheck
```

Requires Python 3.10+.

## Authenticate

Generate an API key from the InCheck admin (`/admin/api-keys` — Teams
plan + admin role) and set the env var:

```bash
export INCHECK_API_KEY="incheck_prod_..."
```

Your key is bound to one organization. InCheck derives a **namespace**
from your org's subdomain — every `org_id` you use must start with
`<namespace>_`. Cross-namespace requests are rejected at the gateway.

## EMS mode — no setup, just chat

```python
from incheck import Client

with Client() as client:
    reply = client.chat.send(
        "Adult dose of atropine for symptomatic bradycardia?",
        scope="ALS",
        state="Massachusetts",
    )
    print(reply.content)
```

That's it. The model answers from general EMS knowledge under the
given `scope`/`state`. No `org_id` needed.

## Unified mode — chat with your documents

Onboard documents once (a **Pod**), then chat against that Pod. A Pod
is identified by your `org_id`; you can hold multiple files in the
same Pod and query across all of them.

```python
from incheck import Client

with Client() as client:
    namespace = client.documents.list_orgs().filtered_by
    org_id = f"{namespace}_dispatch"           # your Pod

    # 1. Onboard documents — initiate → upload → complete → poll, in one call.
    status = client.documents.upload(
        org_id,
        files=["./dispatch_sop.pdf", "./policies.docx"],
    )
    print("processed:", status.progress.processed_pages, "pages")

    # 2. Chat against the Pod
    reply = client.chat.send(
        "What's our hazmat escalation policy?",
        org_id=org_id,                          # ← turns on unified mode
        user_id="alice@hospital.org",
    )
    print(reply.content)
```

You can add or update files in the Pod later with `documents.upload(...)`
again, or scope the change with `initiate_update` / `complete_update`.

> **How does the document processing work?** That's our IP. The contract
> you see — upload, wait for the job to complete, query — is the whole
> public surface. If you need deeper guarantees about extraction
> accuracy, retention, or custom pipelines, talk to us.

## Streaming

Both modes support streaming:

```python
for chunk in client.chat.stream("Summarize the SOP.", org_id="acme_dispatch"):
    if chunk.content:
        print(chunk.content, end="", flush=True)
```

## Async

The SDK ships an async client with the same method names:

```python
import asyncio
from incheck import AsyncClient

async def main():
    async with AsyncClient() as client:
        # EMS
        r = await client.chat.send("Adult dose of epinephrine for anaphylaxis?")
        print(r.content)

        # Unified
        await client.documents.upload("acme_dispatch", ["./sop.pdf"])
        r = await client.chat.send("Summarize.", org_id="acme_dispatch")
        print(r.content)

asyncio.run(main())
```

## Environments

| Environment | Base URL | When to use |
|---|---|---|
| `production` | `https://api.incheck.ai` | live traffic |
| `staging` | `https://api-acceptance.incheck.ai` | integration testing |

Pick one in code or via env var. Production is the default.

```python
Client(environment="staging")          # explicit
# or: INCHECK_ENVIRONMENT=staging      # via env
```

## Endpoints covered

### Documents

| Method | What it does |
|---|---|
| `client.documents.upload(org_id, files, wait=True)` | one-shot: initiate → upload → complete → poll |
| `client.documents.list_orgs()` | every Pod (`org_id`) under your namespace |
| `client.documents.list(org_id)` | files in a Pod's current version |
| `client.documents.version(org_id)` | metadata about the current version |
| `client.documents.initiate_upload(...)` | low-level — get presigned uploads |
| `client.documents.complete_upload(...)` | low-level — trigger processing |
| `client.documents.initiate_update(...)` | add or replace files in an existing Pod |
| `client.documents.complete_update(...)` | finalise an update |
| `client.documents.job(job_id)` | status snapshot |
| `client.documents.wait_for_job(job_id)` | block until terminal |
| `client.documents.delete_version(org_id, version)` | delete one version |
| `client.documents.delete(org_id)` | delete a whole Pod |

### Chat

| Method | What it does |
|---|---|
| `client.chat.send(content, *, org_id=None, ...)` | aggregated reply (EMS if `org_id` omitted, unified if set) |
| `client.chat.stream(content, *, org_id=None, ...)` | streamed chunks as they arrive |

`AsyncClient` exposes the same methods under the same names.

## Errors

Every non-2xx response becomes a typed exception:

```python
from incheck import (
    Client,
    AuthenticationError,
    PermissionError,
    ValidationError,
    JobFailedError,
    JobTimeoutError,
    RateLimitError,
)

with Client() as client:
    try:
        client.documents.upload("royal_dispatch", ["./sop.pdf"])
    except PermissionError as e:
        print("namespace mismatch:", e)
    except ValidationError as e:
        print("bad request:", e)
    except JobFailedError as e:
        print("processing failed:", e.job_id, e.status)
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

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `INCHECK_API_KEY` | — | required |
| `INCHECK_ENVIRONMENT` | `production` | `production` or `staging` |
| `INCHECK_BASE_URL` | — | full URL override (highest priority) |

You can also pass `api_key=`, `environment=`, and `base_url=` explicitly
to either client.

## Breaking changes since 0.0.1

`chat.send` and `chat.stream` no longer take `org_id` as the first
positional argument. The new signature is:

```python
client.chat.send(content, *, org_id=None, ...)
```

Callers that previously did `chat.send(org_id, content)` should switch
to `chat.send(content, org_id=org_id)`. Omitting `org_id` is the new
EMS-mode shape.

## License

MIT.
