# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""What is retried, and what never is.

A retry is only safe when repeating the request cannot change the outcome. A usage report
retried after its response was lost is usage counted twice -- and usage is what customers are
billed on -- so a POST is never retried unless the connection never opened.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from helpers import ORG_ID, Handler, Recorder

from kaitencloud import (
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    ServiceUnavailableError,
)
from kaitencloud._utils import retry_delay

GROUP = {"id": "g0", "name": "AI quotas", "description": None}
PAGE = {"items": [GROUP], "hasMore": False}
CUSTOMER = {
    "id": "c1",
    "name": "Acme",
    "createdAt": "2026-09-14T12:00:00Z",
    "updatedAt": "2026-09-14T12:00:00Z",
    "createdBy": {"id": "u1"},
    "updatedBy": {"id": "u1"},
}
ORGANIZATION = {"id": ORG_ID, "external_id": "org_2abc", "name": "Acme"}

Step = Callable[[httpx.Request], httpx.Response]


def script(*steps: Step) -> Handler:
    """A fake API giving each request the next scripted answer."""
    pending = list(steps)

    def handler(request: httpx.Request) -> httpx.Response:
        assert pending, "the client sent more requests than were scripted"
        return pending.pop(0)(request)

    return handler


def status(code: int, payload: Any = None, headers: dict[str, str] | None = None) -> Step:
    return lambda request: httpx.Response(code, json=payload, headers=headers)


def fail(error: type[httpx.TransportError]) -> Step:
    def raise_error(request: httpx.Request) -> httpx.Response:
        raise error("scripted failure", request=request)

    return raise_error


def test_a_read_is_retried_after_a_server_error(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(503), status(200, PAGE)))
    assert len(client.entitlement_groups.list()) == 1
    assert len(recorder) == 2
    assert len(delays) == 1


def test_retries_stop_after_max_retries(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(500), status(500), status(500)), max_retries=2)
    with pytest.raises(InternalServerError):
        client.customers.get("acme")
    assert len(recorder) == 3
    assert len(delays) == 2


def test_no_retries_sends_exactly_once(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(503)), max_retries=0)
    with pytest.raises(ServiceUnavailableError):
        client.customers.get("acme")
    assert len(recorder) == 1
    assert delays == []


def test_a_create_is_not_retried_after_a_server_error(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(503)))
    with pytest.raises(ServiceUnavailableError):
        client.customers.create(name="Acme")
    assert len(recorder) == 1


def test_a_usage_report_is_not_retried_when_its_response_is_lost(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(fail(httpx.ReadTimeout)))
    with pytest.raises(APITimeoutError):
        client.instances.report_usage("acme-production", "seats", 1)
    assert len(recorder) == 1


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout])
def test_a_create_is_retried_when_the_request_never_left(
    make_client: Callable[..., Any], delays: list[float], error: type[httpx.TransportError]
) -> None:
    client, recorder = make_client(script(fail(error), status(201, CUSTOMER)))
    assert client.customers.create(name="Acme").name == "Acme"
    assert len(recorder) == 2


def test_a_read_is_retried_after_a_timeout(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(fail(httpx.ReadTimeout), status(200, PAGE)))
    client.entitlement_groups.list()
    assert len(recorder) == 2


def test_a_full_replacement_is_retried(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(502), status(204)))
    client.customers.update("acme", name="Acme")
    assert len(recorder) == 2


def test_setting_a_status_is_retried_because_it_converges(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(503), status(204)))
    client.instances.update_status("acme-production", "HEALTHY")
    assert len(recorder) == 2


def test_a_reorder_is_retried_although_it_is_a_post(
    make_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_client(script(status(503), status(204)))
    client.metadata_fields.reorder(["f1", "f2"])
    assert len(recorder) == 2


def test_ensuring_an_organization_is_retried_because_it_is_an_upsert(
    make_platform_client: Callable[..., Any], delays: list[float]
) -> None:
    client, recorder = make_platform_client(script(status(503), status(200, ORGANIZATION)))
    assert client.organizations.ensure(external_id="org_2abc").id == ORG_ID
    assert len(recorder) == 2


@pytest.mark.parametrize(
    ("code", "error"), [(401, AuthenticationError), (403, PermissionDeniedError)]
)
def test_a_refused_credential_is_never_retried(
    make_client: Callable[..., Any], delays: list[float], code: int, error: type[Exception]
) -> None:
    client, recorder = make_client(script(status(code, {"title": "Refused"})))
    with pytest.raises(error):
        client.customers.list()
    assert len(recorder) == 1


def test_retry_after_is_honoured(make_client: Callable[..., Any], delays: list[float]) -> None:
    client, _ = make_client(script(status(429, headers={"Retry-After": "3"}), status(200, PAGE)))
    client.entitlement_groups.list()
    assert delays == [3.0]


def test_retry_after_is_capped(make_client: Callable[..., Any], delays: list[float]) -> None:
    client, _ = make_client(
        script(status(503, headers={"Retry-After": "86400"}), status(200, PAGE))
    )
    client.entitlement_groups.list()
    assert delays == [60.0]


@pytest.mark.parametrize("attempt", range(8))
def test_backoff_grows_with_jitter_and_stays_bounded(attempt: int) -> None:
    for _ in range(50):
        delay = retry_delay(attempt)
        assert min(0.25 * 2**attempt, 8.0) <= delay <= 8.0


def test_the_async_client_retries_the_same_way(
    make_async_client: Callable[..., Any], delays: list[float]
) -> None:
    async def scenario() -> Recorder:
        client, recorder = make_async_client(script(status(503), status(200, PAGE)))
        await client.entitlement_groups.list()
        return recorder

    assert len(asyncio.run(scenario())) == 2
    assert len(delays) == 1
