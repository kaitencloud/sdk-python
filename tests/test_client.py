# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Building clients: credentials, base URLs, headers, options and lifecycle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from helpers import BASE_URL, PLATFORM_URL, Recorder, recording, respond

import kaitencloud
from kaitencloud import (
    AsyncKaitenClient,
    CredentialError,
    KaitenClient,
    KaitenPlatformClient,
)

EMPTY_PAGE = {"items": [], "hasMore": False}


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://kaiten.example.com", "https://kaiten.example.com/api/"),
        ("https://kaiten.example.com/", "https://kaiten.example.com/api/"),
        ("https://kaiten.example.com/api", "https://kaiten.example.com/api/"),
        ("https://kaiten.example.com/api/", "https://kaiten.example.com/api/"),
        ("http://localhost:6000", "http://localhost:6000/api/"),
        ("https://example.com/kaiten/api", "https://example.com/kaiten/api/"),
        ("  https://example.com/prefix  ", "https://example.com/prefix/api/"),
    ],
)
def test_the_base_url_always_ends_under_api(given: str, expected: str) -> None:
    assert KaitenClient(token="ksh_x", base_url=given).base_url == expected


@pytest.mark.parametrize("given", ["kaiten.example.com", "ftp://kaiten.test", "/api"])
def test_the_base_url_must_be_an_absolute_http_url(given: str) -> None:
    with pytest.raises(ValueError, match="base_url"):
        KaitenClient(token="ksh_x", base_url=given)


@pytest.mark.parametrize("configured", [None, "", "   "], ids=["unset", "empty", "blank"])
def test_there_is_no_default_address(
    monkeypatch: pytest.MonkeyPatch, configured: str | None
) -> None:
    """Every deployment has its own address, so the SDK never guesses one to send a token to."""
    if configured is None:
        monkeypatch.delenv("KAITEN_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("KAITEN_BASE_URL", configured)
    with pytest.raises(ValueError, match="KAITEN_BASE_URL"):
        KaitenClient(token="ksh_x")


def test_the_environment_provides_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAITEN_BASE_URL", "https://kaiten.acme.internal")
    monkeypatch.setenv("KAITEN_AUTH_TOKEN", "ksh_from_env")
    recorder = Recorder()
    http_client = httpx.Client(transport=recording(respond(200, EMPTY_PAGE), recorder))

    client = KaitenClient(http_client=http_client)
    client.customers.list()

    assert client.base_url == "https://kaiten.acme.internal/api/"
    assert recorder.only.headers["authorization"] == "Bearer ksh_from_env"


def test_a_client_without_a_credential_is_refused() -> None:
    with pytest.raises(CredentialError, match="KAITEN_AUTH_TOKEN"):
        KaitenClient()


def test_the_platform_client_has_no_default_address() -> None:
    with pytest.raises(ValueError, match="KAITEN_PLATFORM_BASE_URL"):
        KaitenPlatformClient(token="ksm_x")


def test_the_platform_client_reads_its_own_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAITEN_PLATFORM_BASE_URL", PLATFORM_URL)
    monkeypatch.setenv("KAITEN_PLATFORM_TOKEN", "ksm_from_env")
    assert KaitenPlatformClient().base_url == f"{PLATFORM_URL}/api/"


def test_requests_carry_the_credential_and_name_the_sdk(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(
        respond(200, EMPTY_PAGE), default_headers={"X-Request-Source": "billing"}
    )
    client.customers.list()

    request = recorder.only
    assert str(request.url).startswith(f"{BASE_URL}/api/customers?")
    assert request.headers["authorization"] == "Bearer ksh_test"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"].startswith(f"kaitencloud-python/{kaitencloud.__version__}")
    assert request.headers["x-request-source"] == "billing"


def test_default_headers_cannot_replace_the_credential(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(
        respond(200, EMPTY_PAGE), default_headers={"Authorization": "Bearer ksh_other"}
    )
    client.customers.list()
    assert recorder.only.headers["authorization"] == "Bearer ksh_test"


def test_a_token_provider_is_asked_before_every_request(make_client: Callable[..., Any]) -> None:
    tokens = iter(["ksh_first", "ksh_rotated"])
    client, recorder = make_client(respond(200, EMPTY_PAGE), token=lambda: next(tokens))

    client.customers.list()
    client.customers.list()

    assert [request.headers["authorization"] for request in recorder] == [
        "Bearer ksh_first",
        "Bearer ksh_rotated",
    ]


def test_an_async_token_provider_can_be_a_coroutine_function(
    make_async_client: Callable[..., Any],
) -> None:
    async def provide() -> str:
        return "ksh_from_vault"

    async def scenario() -> Recorder:
        client, recorder = make_async_client(respond(200, EMPTY_PAGE), token=provide)
        await client.customers.list()
        return recorder

    assert asyncio.run(scenario()).only.headers["authorization"] == "Bearer ksh_from_vault"


@pytest.mark.parametrize("token", ["ksm_platform", "whsec_c2lnbmluZw=="])
def test_the_core_client_refuses_other_credentials_before_sending(
    make_client: Callable[..., Any], token: str
) -> None:
    client, recorder = make_client(respond(200, EMPTY_PAGE), token=token)
    with pytest.raises(CredentialError):
        client.customers.list()
    assert not recorder


def test_a_rotated_token_of_the_wrong_class_is_caught_too(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, EMPTY_PAGE), token=lambda: "ksm_rotated")
    with pytest.raises(CredentialError, match="KaitenPlatformClient"):
        client.customers.list()
    assert not recorder


@pytest.mark.parametrize("token", ["ksh_organization", "eyJhbGciOiJIUzI1NiJ9.e30.c2ln"])
def test_the_platform_client_accepts_only_platform_credentials(
    make_platform_client: Callable[..., Any], token: str
) -> None:
    client, recorder = make_platform_client(respond(200, {}), token=token)
    with pytest.raises(CredentialError, match="ksm_"):
        client.me()
    assert not recorder


def test_with_options_changes_only_what_it_names_and_shares_the_pool(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(200, EMPTY_PAGE), max_retries=3)

    tuned = client.with_options(max_retries=0, timeout=5.0)
    tuned.customers.list()

    assert (client.max_retries, tuned.max_retries) == (3, 0)
    assert tuned.base_url == client.base_url
    assert tuned._api.http_client is client._api.http_client
    assert tuned.customers is not client.customers
    assert recorder.only.extensions["timeout"] == httpx.Timeout(5.0).as_dict()


def test_closing_a_client_leaves_an_injected_pool_open() -> None:
    injected = httpx.Client(transport=httpx.MockTransport(respond(200, EMPTY_PAGE)))
    with KaitenClient(token="ksh_x", base_url=BASE_URL, http_client=injected) as client:
        client.customers.list()
    assert not injected.is_closed


def test_closing_a_client_closes_the_pool_it_built() -> None:
    client = KaitenClient(token="ksh_x", base_url=BASE_URL)
    client.close()
    assert client._api.http_client.is_closed


def test_the_async_client_is_an_async_context_manager() -> None:
    async def scenario() -> bool:
        async with AsyncKaitenClient(token="ksh_x", base_url=BASE_URL) as client:
            pass
        return client._api.http_client.is_closed

    assert asyncio.run(scenario())


def test_negative_retries_are_refused() -> None:
    with pytest.raises(ValueError, match="max_retries"):
        KaitenClient(token="ksh_x", base_url=BASE_URL, max_retries=-1)


def test_a_client_repr_names_its_base_url() -> None:
    client = KaitenClient(token="ksh_x", base_url=BASE_URL)
    assert repr(client) == "KaitenClient(base_url='https://kaiten.test/api/')"
    assert repr(client.customers) == "<Customers base_url='https://kaiten.test/api/'>"


def test_the_webhooks_module_loads_on_first_access() -> None:
    assert kaitencloud.webhooks.verify_webhook.__name__ == "verify_webhook"
    with pytest.raises(AttributeError):
        _ = kaitencloud.not_a_module  # type: ignore[attr-defined]
