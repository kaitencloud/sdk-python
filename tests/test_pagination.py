# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""List methods walk every page, and refuse to hand back a list they know is partial.

Kaiten's default page is 50 rows. A list method that returned one page would keep working
right up to the day the 51st row was created, and then silently omit it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from contract import sample
from helpers import Handler, Recorder, respond

from kaitencloud import APIResponseValidationError, AuthenticationError, PaginationError

GROUP = {"id": "g0", "name": "AI quotas", "description": None, "slug": "ai-quotas"}


def groups(count: int) -> list[dict[str, Any]]:
    return [{**GROUP, "id": f"g{index}", "slug": f"group-{index}"} for index in range(count)]


def rows_of(schema: str, count: int) -> list[dict[str, Any]]:
    row = sample({"$ref": f"#/components/schemas/{schema}"}, "core")
    return [{**row, "id": f"row-{index}"} for index in range(count)]


def paged(rows: list[dict[str, Any]]) -> Handler:
    """A fake list endpoint that pages the way Kaiten does, honouring limit and cursor."""

    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params["limit"])
        start = int(request.url.params.get("cursor", "0"))
        end = min(start + limit, len(rows))
        page: dict[str, Any] = {"items": rows[start:end], "hasMore": end < len(rows)}
        if end < len(rows):
            page["nextCursor"] = str(end)
        return httpx.Response(200, json=page)

    return handler


def test_a_list_walks_every_page_at_the_largest_page_size(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(paged(groups(451)))

    result = client.entitlement_groups.list()

    assert [group.slug for group in result] == [f"group-{index}" for index in range(451)]
    assert [request.url.params["limit"] for request in recorder] == ["200", "200", "200"]
    assert [request.url.params.get("cursor") for request in recorder] == [None, "200", "400"]


def test_an_empty_collection_is_an_empty_list(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, {"items": [], "hasMore": False}))
    assert client.entitlement_groups.list() == []
    assert len(recorder) == 1


def test_an_endpoint_filter_survives_every_page(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(paged(rows_of("MetadataField", 300)))

    fields = client.metadata_fields.list("DEPLOYMENT_ZONE")

    assert len(fields) == 300
    assert len(recorder) == 2
    assert {request.url.params["resourceType"] for request in recorder} == {"DEPLOYMENT_ZONE"}


def test_a_limit_is_a_ceiling_and_no_page_asks_for_more_than_is_left(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(paged(rows_of("AuditTrail", 1000)))

    entries = client.instances.list_audit_trails("acme-production", limit=250)

    assert len(entries) == 250
    assert [request.url.params["limit"] for request in recorder] == ["200", "50"]


def test_a_limit_below_one_is_refused(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(paged([]))
    with pytest.raises(ValueError, match="limit"):
        client.instances.list_audit_trails("acme-production", limit=0)
    assert not recorder


@pytest.mark.parametrize(
    "page",
    [
        {"items": [GROUP], "hasMore": True},
        {"items": [GROUP], "hasMore": True, "nextCursor": ""},
    ],
    ids=["no cursor", "empty cursor"],
)
def test_more_rows_without_a_cursor_is_an_error_not_a_short_list(
    make_client: Callable[..., Any], page: dict[str, Any]
) -> None:
    client, _ = make_client(respond(200, page))
    with pytest.raises(PaginationError):
        client.entitlement_groups.list()


def test_a_cursor_that_does_not_move_is_an_error_not_a_loop(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(
        respond(200, {"items": [GROUP], "hasMore": True, "nextCursor": "stuck"})
    )
    with pytest.raises(PaginationError):
        client.entitlement_groups.list()
    assert len(recorder) == 2


def test_a_deployment_older_than_pagination_answers_a_bare_array(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(200, groups(3)))
    assert len(client.entitlement_groups.list()) == 3
    assert len(recorder) == 1


def test_an_error_during_the_walk_keeps_its_status(make_client: Callable[..., Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "cursor" in request.url.params:
            return httpx.Response(401, json={"title": "Unauthorized", "detail": "token revoked"})
        return httpx.Response(200, json={"items": [GROUP], "hasMore": True, "nextCursor": "1"})

    client, _ = make_client(handler)
    with pytest.raises(AuthenticationError) as caught:
        client.entitlement_groups.list()
    assert caught.value.status_code == 401
    assert caught.value.detail == "token revoked"


def test_an_answer_that_is_not_a_page_is_a_validation_error(
    make_client: Callable[..., Any],
) -> None:
    client, _ = make_client(respond(200, {"data": []}))
    with pytest.raises(APIResponseValidationError, match="page"):
        client.entitlement_groups.list()


def test_the_async_client_walks_the_same_way(make_async_client: Callable[..., Any]) -> None:
    async def scenario() -> tuple[int, Recorder]:
        client, recorder = make_async_client(paged(groups(451)))
        return len(await client.entitlement_groups.list()), recorder

    count, recorder = asyncio.run(scenario())
    assert count == 451
    assert len(recorder) == 3
