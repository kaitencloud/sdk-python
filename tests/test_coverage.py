# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The clients wrap the whole contract -- and nothing but the contract.

``openapi/coverage.yaml`` maps every operation to the method(s) that call it. These tests fail
when a contract sync adds an operation nobody wrapped, when a mapped method goes missing, when
a client grows a public method nothing maps, or when the sync and async clients disagree on a
signature.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any

import pytest
from contract import coverage, operations
from helpers import BASE_URL, PLATFORM_URL

from kaitencloud import (
    AsyncKaitenClient,
    AsyncKaitenPlatformClient,
    KaitenClient,
    KaitenPlatformClient,
)

SURFACES = ["core", "platform"]
LIFECYCLE = {"close", "with_options"}


@pytest.fixture
def clients(request: pytest.FixtureRequest) -> Iterator[tuple[Any, Any]]:
    if request.param == "core":
        pair: tuple[Any, Any] = (
            KaitenClient(token="ksh_x", base_url=BASE_URL),
            AsyncKaitenClient(token="ksh_x", base_url=BASE_URL),
        )
    else:
        pair = (
            KaitenPlatformClient(token="ksm_x", base_url=PLATFORM_URL),
            AsyncKaitenPlatformClient(token="ksm_x", base_url=PLATFORM_URL),
        )
    yield pair
    pair[0].close()


def mapped_methods(surface: str) -> set[str]:
    methods: set[str] = set()
    for target in coverage()[surface]["operations"].values():
        methods.update([target] if isinstance(target, str) else target)
    return methods


def resolve(client: Any, dotted: str) -> Any:
    target = client
    for part in dotted.split("."):
        target = getattr(target, part)
    return target


def public_methods(client: Any) -> set[str]:
    exposed = {
        name
        for name, _ in inspect.getmembers(type(client), inspect.isfunction)
        if not name.startswith("_") and name not in LIFECYCLE
    }
    for namespace, resource in vars(client).items():
        if namespace.startswith("_"):
            continue
        exposed |= {
            f"{namespace}.{name}"
            for name, _ in inspect.getmembers(type(resource), inspect.isfunction)
            if not name.startswith("_")
        }
    return exposed


@pytest.mark.parametrize("surface", SURFACES)
def test_every_operation_is_mapped_or_excluded_for_a_reason(surface: str) -> None:
    section = coverage()[surface]
    mapped = set(section["operations"])
    excluded = dict(section["excluded"] or {})
    published = {operation.operation_id for operation in operations(surface)}

    assert published - mapped - set(excluded) == set(), "operations nobody wrapped"
    assert (mapped | set(excluded)) - published == set(), "entries for operations that are gone"
    assert mapped & set(excluded) == set()
    assert all(isinstance(reason, str) and reason.strip() for reason in excluded.values())


@pytest.mark.parametrize("clients", SURFACES, indirect=True)
def test_every_mapped_method_exists_on_both_clients_with_one_signature(
    clients: tuple[Any, Any],
) -> None:
    sync_client, async_client = clients
    surface = "platform" if isinstance(sync_client, KaitenPlatformClient) else "core"

    for dotted in sorted(mapped_methods(surface)):
        sync_method = resolve(sync_client, dotted)
        async_method = resolve(async_client, dotted)
        assert not inspect.iscoroutinefunction(sync_method), dotted
        assert inspect.iscoroutinefunction(async_method), dotted
        assert inspect.signature(sync_method) == inspect.signature(async_method), dotted


@pytest.mark.parametrize("clients", SURFACES, indirect=True)
def test_no_public_method_escapes_the_map(clients: tuple[Any, Any]) -> None:
    sync_client, async_client = clients
    surface = "platform" if isinstance(sync_client, KaitenPlatformClient) else "core"

    assert public_methods(sync_client) == mapped_methods(surface)
    assert public_methods(async_client) == mapped_methods(surface)
