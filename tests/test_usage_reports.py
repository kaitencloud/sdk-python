# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Usage report keys, and the usage history.

A ``transaction_id`` makes a report idempotent on the server, so it is the one thing that
makes retrying a report safe: a report is retried with a key and never without one. A key
already used for another report is a client bug, refused with its own error.
"""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from contract import sample
from helpers import Recorder, body, respond

from kaitencloud import (
    APIStatusError,
    PaginationError,
    ServiceUnavailableError,
    ThresholdExceededError,
    TransactionIdReusedError,
    UnprocessableEntityError,
)

USAGE = sample({"$ref": "#/components/schemas/EntitlementUsage"}, "core")
REPORT = sample({"$ref": "#/components/schemas/UsageReport"}, "core")


def problem(status: int, code: str, **extra: Any) -> httpx.Response:
    return httpx.Response(
        status,
        json={"title": "Error", "status": status, "code": code, **extra},
        headers={"content-type": "application/problem+json"},
    )


def in_turn(*answers: Callable[[httpx.Request], httpx.Response]) -> Callable[..., httpx.Response]:
    """Answer the nth request with the nth answer, the last one repeating."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        answer = answers[min(calls["n"], len(answers) - 1)]
        calls["n"] += 1
        return answer(request)

    return handler


def test_the_key_is_sent_only_when_given(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, USAGE))
    client.instances.report_usage("acme", "tokens", 1200, transaction_id="llm-call:9f2c:tokens")
    client.instances.report_usage("acme", "tokens", 1)
    assert body(recorder[0])["transactionId"] == "llm-call:9f2c:tokens"
    assert "transactionId" not in body(recorder[1])


def test_a_keyed_report_is_retried_under_the_same_key(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(
        in_turn(
            lambda _: problem(503, "ReportEntitlementUsageMetric.LedgerUnavailable"),
            lambda _: httpx.Response(200, json=USAGE),
        )
    )
    client.instances.report_usage("acme", "tokens", 1200, transaction_id="evt-1")
    assert [body(request)["transactionId"] for request in recorder] == ["evt-1", "evt-1"]
    assert len(delays) == 1


def test_an_unkeyed_report_is_never_retried(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(503, {"title": "Unavailable"}))
    with pytest.raises(ServiceUnavailableError):
        client.instances.report_usage("acme", "tokens", 1)
    assert len(recorder) == 1


@pytest.mark.parametrize(
    ("code", "expected", "not_expected"),
    [
        (
            "ReportEntitlementUsageMetric.TransactionIdReused",
            TransactionIdReusedError,
            ThresholdExceededError,
        ),
        (
            "ReportEntitlementUsageMetric.ThresholdExceeded",
            ThresholdExceededError,
            TransactionIdReusedError,
        ),
    ],
)
def test_a_conflict_is_named_by_its_code(
    make_client: Callable[..., Any],
    code: str,
    expected: type[APIStatusError],
    not_expected: type[APIStatusError],
) -> None:
    client, recorder = make_client(
        lambda _: problem(
            409, code, errors=[{"location": "body.transactionId", "value": {"reportSeq": 2}}]
        )
    )
    with pytest.raises(expected) as raised:
        client.instances.report_usage("acme", "tokens", 1, transaction_id="evt-1")
    assert not isinstance(raised.value, not_expected)
    assert raised.value.code == code
    assert len(recorder) == 1, "a conflict is never retried"


@pytest.mark.parametrize("key", ["has space", "x" * 129, "a/b", ""])
def test_a_malformed_key_is_refused_before_sending(
    make_client: Callable[..., Any], key: str
) -> None:
    client, recorder = make_client(respond(200, USAGE))
    with pytest.raises(ValueError, match="transaction_id"):
        client.instances.report_usage("acme", "tokens", 1, transaction_id=key)
    assert len(recorder) == 0


def test_the_detailed_report_reads_what_the_server_said(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(
        respond(
            200,
            USAGE,
            headers={"Idempotent-Replayed": "true", "Kaiten-Metadata-Dropped": "too_large"},
        )
    )
    result = client.instances.report_usage_detailed("acme", "tokens", 1, transaction_id="evt-1")
    assert result.replayed
    assert result.metadata_dropped

    plain, _ = make_client(respond(200, USAGE))
    result = plain.instances.report_usage_detailed("acme", "tokens", 1)
    assert not result.replayed
    assert not result.metadata_dropped


def test_an_api_without_keys_gets_the_report_resent_without_one(
    make_client: Callable[..., Any], caplog: pytest.LogCaptureFixture
) -> None:
    refused = {
        "title": "Unprocessable Entity",
        "status": 422,
        "code": "UNPROCESSABLE",
        "errors": [{"location": "body.transactionId", "message": "unexpected property"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "transactionId" in (body(request) or {}):
            return httpx.Response(422, json=refused)
        return httpx.Response(200, json=USAGE)

    client, recorder = make_client(handler)
    with caplog.at_level(logging.WARNING, logger="kaitencloud"):
        client.instances.report_usage("acme", "tokens", 1, transaction_id="evt-1")
        client.instances.report_usage("acme", "tokens", 2, transaction_id="evt-2")

    assert len(recorder) == 3
    assert "transactionId" not in body(recorder[1])
    assert "transactionId" not in body(recorder[2]), "later reports go out without a key"
    warnings = [record for record in caplog.records if "transaction IDs" in record.getMessage()]
    assert len(warnings) == 1


def test_a_new_apis_malformed_key_code_is_not_an_old_api(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(
        lambda _: problem(
            422,
            "ReportEntitlementUsageMetric.InvalidTransactionId",
            errors=[{"location": "body.transactionId", "message": "invalid"}],
        )
    )
    with pytest.raises(UnprocessableEntityError):
        client.instances.report_usage("acme", "tokens", 1, transaction_id="evt-1")
    assert len(recorder) == 1


def test_the_async_client_retries_a_keyed_report_too(make_async_client: Callable[..., Any]) -> None:
    async def scenario() -> Recorder:
        client, recorder = make_async_client(
            in_turn(lambda _: httpx.Response(502), lambda _: httpx.Response(200, json=USAGE))
        )
        async with client:
            result = await client.instances.report_usage_detailed(
                "acme", "tokens", 1, transaction_id="evt-1"
            )
            assert not result.replayed
        return recorder

    assert len(asyncio.run(scenario())) == 2


def page(seqs: list[int], next_after_seq: int | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"items": [{**REPORT, "reportSeq": seq} for seq in seqs]}
    if next_after_seq is not None:
        payload["nextAfterSeq"] = next_after_seq
    return payload


def test_the_history_walks_its_pages(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("kaitencloud._sync.resources.instances._USAGE_HISTORY_PAGE", 2)
    client, recorder = make_client(
        in_turn(
            lambda _: httpx.Response(200, json=page([1, 2], 2)),
            lambda _: httpx.Response(200, json=page([3], None)),
        )
    )
    reports = client.instances.list_usage_reports("acme", "tokens", from_="2026-10-01T00:00:00Z")
    assert [report.report_seq for report in reports] == [1, 2, 3]
    assert recorder[0].url.path.endswith("/instances/acme/entitlements/tokens/usage/reports")
    assert "afterSeq" not in recorder[0].url.params
    assert recorder[1].url.params["afterSeq"] == "2"
    assert recorder[0].url.params["from"] == "2026-10-01T00:00:00Z"


def test_the_history_stops_at_its_limit(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, page([1, 2], 2)))
    reports = client.instances.list_usage_reports("acme", "tokens", limit=2)
    assert len(reports) == 2
    assert recorder.only.url.params["limit"] == "2"


def test_a_cursor_that_does_not_move_is_refused(
    make_client: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("kaitencloud._sync.resources.instances._USAGE_HISTORY_PAGE", 2)
    client, _ = make_client(respond(200, page([1, 2], 2)))
    with pytest.raises(PaginationError):
        client.instances.list_usage_reports("acme", "tokens")


def test_an_export_streams_into_its_destination(make_client: Callable[..., Any]) -> None:
    csv = b"organization_id,instance_id\no,i\n"
    client, recorder = make_client(respond(200, csv, headers={"content-type": "text/csv"}))
    destination = io.BytesIO()
    written = client.instances.export_usage_reports("acme", "tokens", destination, format="json")
    assert written == len(csv)
    assert destination.getvalue() == csv
    assert recorder.only.url.params["format"] == "json"


def test_an_export_refusal_raises_with_its_code(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(lambda _: problem(422, "ExportUsageReports.OutsideRetention"))
    destination = io.BytesIO()
    with pytest.raises(UnprocessableEntityError) as raised:
        client.instances.export_organization_usage_reports(
            destination, from_="2025-01-01T00:00:00Z"
        )
    assert raised.value.code == "ExportUsageReports.OutsideRetention"
    assert destination.getvalue() == b""


def test_an_export_retries_an_unavailable_api_before_writing(
    make_async_client: Callable[..., Any],
) -> None:
    async def scenario() -> tuple[int, Recorder, bytes]:
        client, recorder = make_async_client(
            in_turn(lambda _: httpx.Response(503), lambda _: httpx.Response(200, content=b"a,b\n"))
        )
        destination = io.BytesIO()
        async with client:
            written = await client.instances.export_organization_usage_reports(destination)
        return written, recorder, destination.getvalue()

    written, recorder, content = asyncio.run(scenario())
    assert (written, len(recorder), content) == (4, 2, b"a,b\n")
