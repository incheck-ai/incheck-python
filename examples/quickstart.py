"""End-to-end live smoke test against the real InCheck platform.

Run as a customer would: one script, one API key, one PDF, one chat.
If this prints expected output without raising, the SDK works.

Usage:
    export INCHECK_API_KEY="incheck_acceptance_..."
    uv run python examples/quickstart.py path/to/doc.pdf

If a path is omitted, the script picks the small test PDF that lives in
policy-doc-agent/dev/ during local dev. Customers always pass their own.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from incheck import Client, IncheckError, JobFailedError, JobTimeoutError


def _resolve_namespace(client: Client) -> str:
    orgs = client.documents.list_orgs()
    if not orgs.filtered_by:
        raise SystemExit("No namespace returned for this API key — is the org configured?")
    return orgs.filtered_by


def main() -> int:
    if not os.environ.get("INCHECK_API_KEY"):
        print("ERROR: INCHECK_API_KEY is not set", file=sys.stderr)
        return 2

    if len(sys.argv) >= 2:
        pdf = Path(sys.argv[1]).expanduser().resolve()
    else:
        pdf = (
            Path.home()
            / "fastmedical/policy-doc-agent/dev/test_pdf_without_toc.pdf"
        )
    if not pdf.exists():
        print(f"ERROR: file not found: {pdf}", file=sys.stderr)
        return 2

    # Until prod cuts over, target the staging environment explicitly.
    # Once prod is live, drop the kwarg — `Client()` defaults to production.
    with Client(environment="staging") as client:
        namespace = _resolve_namespace(client)
        print(f"Namespace: {namespace}")

        org_id = f"{namespace}_sdkdemo"
        print(f"Target org_id: {org_id}\n")

        # ---------------- Upload ----------------
        print(f"Uploading {pdf.name} → {org_id} …")
        try:
            status = client.documents.upload(
                org_id, [pdf], wait=True, timeout=600, poll_interval=15
            )
        except JobFailedError as e:
            print(f"job failed: {e}  (job_id={e.job_id}, status={e.status})", file=sys.stderr)
            return 1
        except JobTimeoutError as e:
            print(
                f"job timed out: {e}  (job_id={e.job_id}, last={e.last_status})",
                file=sys.stderr,
            )
            return 1
        print(
            f"  job_id={status.job_id}  status={status.status}  "
            f"pages={status.progress.processed_pages}/{status.progress.total_pages}"
        )

        # ---------------- Discoverability ----------------
        docs = client.documents.list(org_id)
        print(f"\nDocuments in {org_id} (version={docs.version}):")
        for d in docs.documents:
            size = f"{d.size_bytes} bytes" if d.size_bytes else "?"
            print(f"  - {d.filename}  {size}")

        # ---------------- Unified mode — chat against the Pod ----------------
        print("\n=== chat #1 (unified mode — grounded in your Pod) ===")
        reply = client.chat.send(
            "What does the uploaded document say? Summarize briefly.",
            org_id=org_id,
            user_id="sdk-smoke",
            conversation_id=str(uuid.uuid4()),
        )
        print(reply.content)

        # ---------------- EMS mode — no Pod, no retrieval ----------------
        print("\n=== chat #2 (EMS mode — general EMS knowledge, no org_id) ===")
        reply = client.chat.send(
            "What is the maximum adult dose of epinephrine for anaphylaxis?",
            user_id="sdk-smoke",
            conversation_id=str(uuid.uuid4()),
            scope="ALS",
            state="Massachusetts",
        )
        print(reply.content)

        # ---------------- Streaming (EMS) ----------------
        print("\n=== chat #3 (streaming, EMS mode) ===")
        for chunk in client.chat.stream(
            "List three bullet points about scene safety.",
            user_id="sdk-smoke",
        ):
            if chunk.content:
                print(chunk.content, end="", flush=True)
        print()

    print("\nOK — SDK end-to-end smoke passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except IncheckError as e:
        print(f"\nInCheck API error: {type(e).__name__}: {e}", file=sys.stderr)
        if e.status_code is not None:
            print(f"  status_code={e.status_code}", file=sys.stderr)
        if e.response_body is not None:
            print(f"  response_body={e.response_body!r}", file=sys.stderr)
        sys.exit(1)
