# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Fixtures: clients wired to in-process fake APIs, so no test opens a socket."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from helpers import BASE_URL, PLATFORM_URL, Handler, Recorder, recording

from kaitencloud import (
    AsyncKaitenClient,
    AsyncKaitenPlatformClient,
    KaitenClient,
    KaitenPlatformClient,
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's own Kaiten configuration out of every test."""
    for name in (
        "KAITEN_BASE_URL",
        "KAITEN_AUTH_TOKEN",
        "KAITEN_PLATFORM_BASE_URL",
        "KAITEN_PLATFORM_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def delays(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """The retry delays the clients asked for, recorded instead of slept."""
    recorded: list[float] = []

    async def async_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr("kaitencloud._sync._http.sleep", recorded.append)
    monkeypatch.setattr("kaitencloud._async._http.async_sleep", async_sleep)
    return recorded


@pytest.fixture
def make_client(delays: list[float]) -> Callable[..., tuple[KaitenClient, Recorder]]:
    def factory(handler: Handler, **options: Any) -> tuple[KaitenClient, Recorder]:
        recorder = Recorder()
        options.setdefault("token", "ksh_test")
        options.setdefault("base_url", BASE_URL)
        http_client = httpx.Client(transport=recording(handler, recorder))
        return KaitenClient(http_client=http_client, **options), recorder

    return factory


@pytest.fixture
def make_async_client(delays: list[float]) -> Callable[..., tuple[AsyncKaitenClient, Recorder]]:
    def factory(handler: Handler, **options: Any) -> tuple[AsyncKaitenClient, Recorder]:
        recorder = Recorder()
        options.setdefault("token", "ksh_test")
        options.setdefault("base_url", BASE_URL)
        http_client = httpx.AsyncClient(transport=recording(handler, recorder))
        return AsyncKaitenClient(http_client=http_client, **options), recorder

    return factory


@pytest.fixture
def make_platform_client(
    delays: list[float],
) -> Callable[..., tuple[KaitenPlatformClient, Recorder]]:
    def factory(handler: Handler, **options: Any) -> tuple[KaitenPlatformClient, Recorder]:
        recorder = Recorder()
        options.setdefault("token", "ksm_test")
        options.setdefault("base_url", PLATFORM_URL)
        http_client = httpx.Client(transport=recording(handler, recorder))
        return KaitenPlatformClient(http_client=http_client, **options), recorder

    return factory


@pytest.fixture
def make_async_platform_client(
    delays: list[float],
) -> Callable[..., tuple[AsyncKaitenPlatformClient, Recorder]]:
    def factory(handler: Handler, **options: Any) -> tuple[AsyncKaitenPlatformClient, Recorder]:
        recorder = Recorder()
        options.setdefault("token", "ksm_test")
        options.setdefault("base_url", PLATFORM_URL)
        http_client = httpx.AsyncClient(transport=recording(handler, recorder))
        return AsyncKaitenPlatformClient(http_client=http_client, **options), recorder

    return factory
