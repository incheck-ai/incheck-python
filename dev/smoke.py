"""End-to-end smoke test for the InCheck Python SDK.

Exercises every public surface against a real environment:

  1. EMS mode — non-streaming + streaming, default and varied scope/state
  2. Pod onboarding — upload a tiny markdown doc and wait for processing
  3. Unified mode — non-streaming + streaming chat against the new Pod
  4. Multiple Pods — onboard a second Pod and verify each is independently
     queryable via its own org_id

Usage:
    INCHECK_API_KEY=incheck_acceptance_... \\
        INCHECK_ENVIRONMENT=staging \\
        uv run python dev/smoke.py
"""

from __future__ import annotations

import io
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Iterator

# Gateway rate-limits per tenant. With a single key driving the whole
# test we'd otherwise pile up against it. Prod's window is tighter than
# acceptance — 10s gives a comfortable margin without making the suite
# painfully slow.
CHAT_COOLDOWN_SEC = 10.0


def _cooldown() -> None:
    time.sleep(CHAT_COOLDOWN_SEC)

from incheck import (
    ChatMessage,
    Client,
    JobFailedError,
    JobTimeoutError,
    ValidationError,
)

# Each Pod gets a fresh suffix so re-running the test doesn't collide with
# a stale processing job for the same org_id.
RUN_TAG = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _h(title: str) -> None:
    bar = "=" * (len(title) + 4)
    print(f"\n{bar}\n  {title}\n{bar}")


def _ok(msg: str) -> None:
    print(f"  PASS  {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL  {msg}")


def _info(msg: str) -> None:
    print(f"        {msg}")


def _stream_text(chunks: Iterator) -> tuple[str, int]:
    buf: list[str] = []
    n = 0
    for chunk in chunks:
        if chunk.content:
            buf.append(chunk.content)
            n += 1
    return "".join(buf), n


def _make_pdf(pages: list[list[str]]) -> bytes:
    """Build a multi-page PDF where each inner list is one page of lines."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    _, height = letter
    for page_idx, lines in enumerate(pages):
        c.setFont("Helvetica", 12)
        y = height - 72
        for line in lines:
            c.drawString(72, y, line[:120])
            y -= 18
        if page_idx < len(pages) - 1:
            c.showPage()
    c.save()
    return buf.getvalue()


def _pod_a_pdf() -> tuple[str, io.BytesIO]:
    body = _make_pdf([
        [
            "DISPATCH STANDARD OPERATING PROCEDURE",
            "",
            "Section 1. Hazmat escalation.",
            "",
            "When dispatch identifies a hazmat incident, the on-call hazmat",
            "captain (call sign HAZ-1) is alerted within 90 seconds via the",
            "L3 paging tree. HAZ-1 owns scene command until relieved by Chief.",
        ],
        [
            "Section 2. Cardiac arrest priority dispatch.",
            "",
            "All cardiac-arrest calls receive a code-3 ALS + BLS dual response",
            "with the nearest unit re-routed via override channel 47.",
        ],
    ])
    return f"smoke_dispatch_{RUN_TAG}.pdf", io.BytesIO(body)


def _pod_b_pdf() -> tuple[str, io.BytesIO]:
    body = _make_pdf([
        [
            "WILDERNESS RESCUE PROTOCOL",
            "",
            "Section 1. Rope rescue cadence.",
            "",
            "Two-rope systems use the OREGON-SPIDER configuration. The",
            "main and belay are anchored at independent points and backed",
            "up by a third guardian anchor labelled GUARDIAN-7.",
        ],
        [
            "Section 2. Wildlife perimeter protocol.",
            "",
            "When a large mammal (bear, moose, mountain lion) enters the",
            "rescue zone, the scout call sign TRACER-9 is dispatched to",
            "establish a 50-metre perimeter and report to incident command.",
        ],
    ])
    return f"smoke_wilderness_{RUN_TAG}.pdf", io.BytesIO(body)


def main() -> int:
    api_key = os.environ.get("INCHECK_API_KEY")
    if not api_key:
        print("INCHECK_API_KEY not set", file=sys.stderr)
        return 2

    failures: list[str] = []

    with Client() as client:
        _h(f"0. Discovery (target {client.base_url})")
        orgs = client.documents.list_orgs()
        namespace = orgs.filtered_by
        _ok(f"namespace = {namespace!r}; existing Pods: {len(orgs.org_ids)}")

        # ------------------------------------------------------------------
        _h("1. EMS mode — non-streaming, default ALS / California-LAC")
        try:
            reply = client.chat.send(
                "What's the adult dose of atropine for symptomatic bradycardia?",
                conversation_id=f"smoke-ems-{RUN_TAG}-1",
                user_id="smoke@incheck.ai",
            )
            assert reply.content.strip(), "empty content"
            _ok(f"got {len(reply.content)} chars")
            _info(reply.content[:200].replace("\n", " ") + " ...")
        except Exception as e:
            failures.append(f"EMS non-stream default: {e}")
            traceback.print_exc()

        _cooldown()
        # ------------------------------------------------------------------
        _h("2. EMS mode — streaming, BLS / Massachusetts")
        try:
            full, n_chunks = _stream_text(
                client.chat.stream(
                    "Give me three BLS scene-safety bullets for a vehicle fire.",
                    scope="BLS",
                    state="Massachusetts",
                    conversation_id=f"smoke-ems-{RUN_TAG}-2",
                    user_id="smoke@incheck.ai",
                )
            )
            assert full.strip(), "empty stream"
            assert n_chunks >= 1, f"expected at least 1 chunk, got {n_chunks}"
            _ok(f"{n_chunks} chunk(s), {len(full)} chars")
            _info(full[:200].replace("\n", " ") + " ...")
        except Exception as e:
            failures.append(f"EMS streaming BLS/MA: {e}")
            traceback.print_exc()

        # ------------------------------------------------------------------
        pod_one = f"{namespace}_smokea_{RUN_TAG}"
        pod_two = f"{namespace}_smokeb_{RUN_TAG}"

        _h(f"3. Pod A onboarding — upload 2-page PDF into {pod_one}")
        pod_a_ready = False
        try:
            name, body = _pod_a_pdf()
            status = client.documents.upload(
                pod_one,
                files=[(name, body)],
                wait=True,
                timeout=600,
                poll_interval=15,
            )
            assert status.is_successful(), f"job did not complete: status={status.status}"
            _ok(f"status={status.status}, "
                f"pages={status.progress.processed_pages}/{status.progress.total_pages}")
            pod_a_ready = True
        except (JobFailedError, JobTimeoutError) as e:
            failures.append(f"Pod A onboarding: {e}")
        except Exception as e:
            failures.append(f"Pod A onboarding: {e}")
            traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("4. Unified mode — non-streaming against Pod A (must quote HAZ-1)")
        if not pod_a_ready:
            _info("skipped — Pod A not ready")
        else:
            try:
                reply = client.chat.send(
                    "According to our dispatch SOP, what call sign is the on-call hazmat captain?",
                    org_id=pod_one,
                    conversation_id=f"smoke-uni-{RUN_TAG}-1",
                    user_id="smoke@incheck.ai",
                )
                assert reply.content.strip(), "empty content"
                grounded = "HAZ-1" in reply.content
                _ok(f"got {len(reply.content)} chars; quotes HAZ-1={grounded}")
                _info(reply.content[:300].replace("\n", " ") + " ...")
                if not grounded:
                    failures.append("Unified non-stream Pod A: HAZ-1 not quoted")
            except Exception as e:
                failures.append(f"Unified non-stream Pod A: {e}")
                traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("5. Unified mode — streaming against Pod A (must mention channel 47)")
        if not pod_a_ready:
            _info("skipped — Pod A not ready")
        else:
            try:
                full, n_chunks = _stream_text(
                    client.chat.stream(
                        "Per our SOP, what override channel handles cardiac-arrest re-route?",
                        org_id=pod_one,
                        conversation_id=f"smoke-uni-{RUN_TAG}-2",
                        user_id="smoke@incheck.ai",
                    )
                )
                assert full.strip(), "empty stream"
                assert n_chunks >= 1, f"expected at least 1 chunk, got {n_chunks}"
                grounded = "47" in full
                _ok(f"{n_chunks} chunk(s), {len(full)} chars; mentions 47={grounded}")
                _info(full[:300].replace("\n", " ") + " ...")
                if not grounded:
                    failures.append("Unified streaming Pod A: channel 47 not mentioned")
            except Exception as e:
                failures.append(f"Unified streaming Pod A: {e}")
                traceback.print_exc()

        # ------------------------------------------------------------------
        _h(f"6. Pod B onboarding — distinct 2-page PDF in {pod_two}")
        pod_b_ready = False
        try:
            name, body = _pod_b_pdf()
            status = client.documents.upload(
                pod_two,
                files=[(name, body)],
                wait=True,
                timeout=600,
                poll_interval=15,
            )
            assert status.is_successful(), f"job did not complete: status={status.status}"
            _ok(f"status={status.status}, "
                f"pages={status.progress.processed_pages}/{status.progress.total_pages}")
            pod_b_ready = True
        except Exception as e:
            failures.append(f"Pod B onboarding: {e}")
            traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("7. Multi-Pod isolation — Pod B must quote GUARDIAN-7 and NOT leak HAZ-1")
        if not pod_b_ready:
            _info("skipped — Pod B not ready")
        else:
            try:
                reply_b = client.chat.send(
                    "Per our wilderness protocol, what's the name of the third anchor in our two-rope configuration?",
                    org_id=pod_two,
                    conversation_id=f"smoke-uni-{RUN_TAG}-3",
                    user_id="smoke@incheck.ai",
                )
                has_b = "GUARDIAN-7" in reply_b.content
                _ok(f"Pod B reply quotes GUARDIAN-7: {has_b}")
                _info(reply_b.content[:300].replace("\n", " ") + " ...")
                if not has_b:
                    failures.append("Pod B: GUARDIAN-7 not quoted")

                _cooldown()
                # Page-2 retrieval check on Pod B (TRACER-9 only exists on page 2).
                reply_b_pg2 = client.chat.send(
                    "Per our wilderness protocol, which scout call sign establishes the wildlife perimeter?",
                    org_id=pod_two,
                    conversation_id=f"smoke-uni-{RUN_TAG}-3b",
                    user_id="smoke@incheck.ai",
                )
                has_pg2 = "TRACER-9" in reply_b_pg2.content
                _ok(f"Pod B page-2 fact (TRACER-9) surfaced: {has_pg2}")
                _info(reply_b_pg2.content[:300].replace("\n", " ") + " ...")
                if not has_pg2:
                    failures.append("Pod B: TRACER-9 (page 2) not quoted")

                _cooldown()
                # Pod A's HAZ-1 must NOT leak into Pod B answers.
                reply_b_cross = client.chat.send(
                    "What call sign is our on-call hazmat captain?",
                    org_id=pod_two,
                    conversation_id=f"smoke-uni-{RUN_TAG}-4",
                    user_id="smoke@incheck.ai",
                )
                _info(reply_b_cross.content[:300].replace("\n", " ") + " ...")
                if "HAZ-1" in reply_b_cross.content:
                    failures.append("LEAK: Pod B answer mentioned HAZ-1 which only lives in Pod A")
                else:
                    _ok("Pod B did not leak Pod A's HAZ-1 — isolation good")
            except Exception as e:
                failures.append(f"Multi-Pod isolation: {e}")
                traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("8. Pod A still queryable after Pod B exists")
        if not pod_a_ready:
            _info("skipped — Pod A not ready")
        else:
            try:
                reply_a2 = client.chat.send(
                    "Per our dispatch SOP, what call sign is our hazmat captain?",
                    org_id=pod_one,
                    conversation_id=f"smoke-uni-{RUN_TAG}-5",
                    user_id="smoke@incheck.ai",
                )
                still_grounded = "HAZ-1" in reply_a2.content
                _ok(f"Pod A still quotes HAZ-1: {still_grounded}")
                _info(reply_a2.content[:300].replace("\n", " ") + " ...")
                if not still_grounded:
                    failures.append("Pod A regression: HAZ-1 missing after Pod B exists")
            except Exception as e:
                failures.append(f"Pod A re-query: {e}")
                traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("9. Multi-Pod fan-out — one chat references BOTH Pods (org_id=list)")
        if not (pod_a_ready and pod_b_ready):
            _info("skipped — both Pods required")
        else:
            try:
                # Question deliberately spans both Pods. A single-Pod
                # call could only ground one half — fan-out should
                # surface facts from both A (HAZ-1) and B (GUARDIAN-7).
                reply = client.chat.send(
                    (
                        "Across our dispatch SOP and wilderness protocol, "
                        "name the on-call hazmat captain's call sign AND "
                        "the third (guardian) anchor in our two-rope "
                        "rope-rescue configuration."
                    ),
                    org_id=[pod_one, pod_two],
                    conversation_id=f"smoke-fanout-{RUN_TAG}-1",
                    user_id="smoke@incheck.ai",
                )
                got_a = "HAZ-1" in reply.content
                got_b = "GUARDIAN-7" in reply.content
                _ok(f"answer length={len(reply.content)}; HAZ-1={got_a}, GUARDIAN-7={got_b}")
                _info(reply.content[:400].replace("\n", " ") + " ...")
                if not (got_a and got_b):
                    failures.append(
                        f"Multi-Pod fan-out: expected both HAZ-1 and GUARDIAN-7; got HAZ-1={got_a}, GUARDIAN-7={got_b}"
                    )
            except Exception as e:
                failures.append(f"Multi-Pod fan-out: {e}")
                traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("10. Multi-turn EMS — messages array carries context across turns")
        try:
            # Prior turn establishes "adult atropine for bradycardia".
            # Follow-up asks a deictic question ("And for a child?") that
            # is meaningless without the prior context.
            reply = client.chat.send(
                "And what about for a 6-year-old child?",
                messages=[
                    ChatMessage(
                        role="user",
                        content="What's the adult dose of atropine for symptomatic bradycardia?",
                    ),
                    ChatMessage(
                        role="assistant",
                        content="1 mg IV/IO every 3-5 minutes, max total 3 mg.",
                    ),
                ],
                conversation_id=f"smoke-mt-ems-{RUN_TAG}",
                user_id="smoke@incheck.ai",
            )
            assert reply.content.strip(), "empty content"
            text = reply.content.lower()
            mentions_pediatric = any(
                k in text for k in ("pediatric", "child", "kg", "mg/kg", "0.02")
            )
            _ok(f"got {len(reply.content)} chars; pediatric context picked up={mentions_pediatric}")
            _info(reply.content[:400].replace("\n", " ") + " ...")
            if not mentions_pediatric:
                failures.append(
                    "EMS multi-turn: follow-up did not show pediatric context — likely lost history"
                )
        except Exception as e:
            failures.append(f"EMS multi-turn: {e}")
            traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("11. Multi-turn unified — messages array against Pod A")
        if not pod_a_ready:
            _info("skipped — Pod A required")
        else:
            try:
                reply = client.chat.send(
                    "And what override channel handles their cardiac-arrest re-route?",
                    org_id=pod_one,
                    messages=[
                        ChatMessage(
                            role="user",
                            content="What call sign is our on-call hazmat captain?",
                        ),
                        ChatMessage(
                            role="assistant",
                            content="Per the dispatch SOP, the on-call hazmat captain uses call sign HAZ-1.",
                        ),
                    ],
                    conversation_id=f"smoke-mt-uni-{RUN_TAG}",
                    user_id="smoke@incheck.ai",
                )
                grounded = "47" in reply.content
                _ok(f"got {len(reply.content)} chars; mentions channel 47={grounded}")
                _info(reply.content[:400].replace("\n", " ") + " ...")
                if not grounded:
                    failures.append(
                        "Unified multi-turn: follow-up did not surface channel 47 — retrieval or history broken"
                    )
            except Exception as e:
                failures.append(f"Unified multi-turn: {e}")
                traceback.print_exc()

        # ------------------------------------------------------------------
        _cooldown()
        _h("12. Multi-turn validation — gateway rejects malformed messages")
        try:
            # The SDK doesn't client-side-validate the messages list — we
            # forward dicts as-is — so the gateway's alternation rule
            # is what fires. The 422 is mapped to ValidationError by
            # _transport.handle_response.
            try:
                client.chat.send(
                    "anything",
                    # Invalid: two user turns in a row.
                    messages=[
                        {"role": "user", "content": "a"},
                        {"role": "user", "content": "b"},
                    ],
                    conversation_id=f"smoke-mt-bad-{RUN_TAG}",
                    user_id="smoke@incheck.ai",
                )
            except ValidationError as ve:
                if ve.status_code == 422 and "alternate" in str(ve).lower():
                    _ok(f"SDK surfaced 422 ValidationError: {str(ve)[:200]}")
                else:
                    failures.append(
                        f"Multi-turn validation: expected 422 with alternation error, got {ve.status_code}: {ve}"
                    )
            else:
                failures.append(
                    "Multi-turn validation: expected ValidationError, got success"
                )
        except Exception as e:
            failures.append(f"Multi-turn validation: {e}")
            traceback.print_exc()

        # ------------------------------------------------------------------
        _h("Cleanup — delete the two smoke Pods")
        for pid in (pod_one, pod_two):
            try:
                resp = client.documents.delete(pid)
                _ok(f"deleted {pid} (message={resp.message!r})")
            except Exception as e:
                _info(f"could not delete {pid}: {e}")

    _h("Summary")
    if failures:
        print(f"  FAILURES ({len(failures)}):")
        for f in failures:
            print(f"   - {f}")
        return 1
    print("  ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
