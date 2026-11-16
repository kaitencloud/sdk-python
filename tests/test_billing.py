# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Billing and the usage history: what the contract table cannot see.

The public routes' credentials, the exports' bytes, the usage report's idempotency key and
the history's ``afterSeq`` pages.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from contract import sample
from helpers import body, respond

from kaitencloud import (
    CredentialError,
    PaginationError,
    ServiceUnavailableError,
    ThresholdExceededError,
    TransactionIdReusedError,
)

REPORTED = sample({"$ref": "#/components/schemas/ReportedEntitlementUsage"}, "core")
CATALOG = sample({"$ref": "#/components/schemas/PublicCatalog"}, "core")
REPORT = sample({"$ref": "#/components/schemas/UsageReport"}, "core")
HISTORY = "/api/instances/acme-production/entitlements/seats/usage/reports"


def test_a_publishable_key_travels_in_its_own_header_never_as_a_bearer_token(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(200, CATALOG), token="pk_live_3f6b")
    client.billing.public.get_catalog(include_addons=False)

    request = recorder.only
    assert request.headers["x-kaiten-publishable-key"] == "pk_live_3f6b"
    assert "authorization" not in request.headers
    assert request.url.params["include"] == "none"


@pytest.mark.parametrize(
    ("token", "call"),
    [
        ("ksh_org", lambda c: c.billing.public.get_catalog()),
        ("kst_session", lambda c: c.billing.public.create_checkout_session(turnstile_token="t")),
        ("pk_live", lambda c: c.billing.session.get_portal()),
        ("ksh_org", lambda c: c.billing.session.cancel()),
        ("pk_live", lambda c: c.billing.public.confirm_checkout_session("cs_1")),
    ],
    ids=["catalog", "checkout-start", "session", "session-write", "checkout-confirm"],
)
def test_a_public_route_refuses_any_other_credential_before_sending(
    make_client: Callable[..., Any], token: str, call: Callable[[Any], Any]
) -> None:
    client, recorder = make_client(respond(200, {}), token=token)
    with pytest.raises(CredentialError, match="takes"):
        call(client)
    assert not recorder


def test_invoice_statuses_are_repeated_query_parameters(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, {"items": [], "hasMore": False}))
    client.billing.invoices.list(status=["MANUAL", "PAID"], overdue=True)

    params = recorder.only.url.params
    assert params.get_list("status") == ["MANUAL", "PAID"]
    assert params["overdue"] == "true"


@pytest.mark.parametrize(
    ("export_format", "media_type"), [("csv", "text/csv"), ("json", "application/x-ndjson")]
)
def test_an_export_asks_for_its_format_and_returns_the_bytes(
    make_client: Callable[..., Any], export_format: Any, media_type: str
) -> None:
    client, recorder = make_client(respond(200, "id,total\ninv_1,4900\n"))

    exported = client.billing.invoices.export(format=export_format)

    assert exported == b"id,total\ninv_1,4900\n"
    assert recorder.only.headers["accept"] == media_type
    assert recorder.only.url.params["format"] == export_format


def test_a_limit_below_one_is_refused_before_sending(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, {"items": [], "hasMore": False}))
    with pytest.raises(ValueError, match="at least 1"):
        client.billing.invoices.list(limit=0)
    assert not recorder


def test_a_keyed_usage_report_sends_its_key_and_says_it_was_replayed(
    make_client: Callable[..., Any],
) -> None:
    headers = {"Idempotent-Replayed": "true", "Kaiten-Metadata-Dropped": "too_large"}
    client, recorder = make_client(respond(200, REPORTED, headers=headers))

    result = client.instances.report_usage_detailed(
        "acme-production", "tokens", 1200, transaction_id="llm-call-9f2c:tokens"
    )

    assert recorder.only.headers["idempotency-key"] == "llm-call-9f2c:tokens"
    assert body(recorder.only) == {"value": {"type": "number", "value": 1200}, "behavior": "append"}
    assert (result.replayed, result.metadata_dropped) == (True, True)
    assert result.usage.entitlement_slug == REPORTED["entitlementSlug"]


def test_a_usage_report_without_a_key_sends_none(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, REPORTED))

    result = client.instances.report_usage_detailed("acme-production", "seats", 1)

    assert "idempotency-key" not in recorder.only.headers
    assert (result.replayed, result.metadata_dropped) == (False, False)


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("ReportEntitlementUsageMetric.TransactionIdReused", TransactionIdReusedError),
        ("ReportEntitlementUsageMetric.ThresholdExceeded", ThresholdExceededError),
    ],
    ids=["key-reused", "threshold"],
)
def test_a_refused_usage_report_is_named_by_its_code(
    make_client: Callable[..., Any], code: str, error: type[Exception]
) -> None:
    problem = {"title": "Conflict", "status": 409, "code": code}
    client, _ = make_client(respond(409, problem))

    with pytest.raises(error) as raised:
        client.instances.report_usage_detailed("acme-production", "seats", 1, transaction_id="k1")
    assert type(raised.value) is error


def test_a_keyed_usage_report_is_never_retried(make_client: Callable[..., Any]) -> None:
    # A Kaiten older than keys ignores the header, and would count a resent report twice.
    client, recorder = make_client(respond(503), max_retries=2)
    with pytest.raises(ServiceUnavailableError):
        client.instances.report_usage_detailed("acme-production", "seats", 1, transaction_id="k1")
    assert len(recorder) == 1


def history(count: int, *, stuck: bool = False) -> Callable[[httpx.Request], httpx.Response]:
    """A usage history endpoint paging by afterSeq, as Kaiten does; ``stuck`` never advances."""

    def handler(request: httpx.Request) -> httpx.Response:
        after = int(request.url.params.get("afterSeq", "0"))
        limit = int(request.url.params["limit"])
        rows = [
            {**REPORT, "reportSeq": seq} for seq in range(after + 1, min(after + limit, count) + 1)
        ]
        page: dict[str, Any] = {"items": rows}
        if rows and rows[-1]["reportSeq"] < count:
            page["nextAfterSeq"] = after if stuck else rows[-1]["reportSeq"]
        return httpx.Response(200, json=page)

    return handler


def test_the_usage_history_walks_every_page(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(history(1200))

    reports = client.instances.list_usage_reports("acme-production", "seats")

    assert [report.report_seq for report in reports] == list(range(1, 1201))
    assert [request.url.params.get("afterSeq") for request in recorder] == [None, "500", "1000"]
    assert {request.url.params["limit"] for request in recorder} == {"500"}
    assert {request.url.path for request in recorder} == {HISTORY}


def test_the_usage_history_stops_at_its_ceiling(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(history(1200))

    reports = client.instances.list_usage_reports("acme-production", "seats", limit=3)

    assert [report.report_seq for report in reports] == [1, 2, 3]
    assert recorder.only.url.params["limit"] == "3"


def test_a_history_page_that_does_not_advance_is_refused(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(history(1200, stuck=True))
    with pytest.raises(PaginationError, match="afterSeq"):
        client.instances.list_usage_reports("acme-production", "seats")


def test_the_async_client_walks_the_history_too(make_async_client: Callable[..., Any]) -> None:
    async def scenario() -> list[int]:
        client, _ = make_async_client(history(700))
        async with client:
            reports = await client.billing.invoices.list_line_reports("inv_1", "line_1")
        return [report.report_seq for report in reports]

    assert asyncio.run(scenario()) == list(range(1, 701))
