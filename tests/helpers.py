# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Test helpers: a recording fake API, and the values tests share."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

BASE_URL = "https://kaiten.test"
PLATFORM_URL = "http://kaiten-api.internal:6001"
ORG_ID = "3f6b1a2c-7c1e-4d0b-9d5f-2b0a1c4e8d31"
USER_ID = "8a1f0e2b-1c3d-4e5f-9a7b-6c5d4e3f2a1b"

Handler = Callable[[httpx.Request], httpx.Response]


class Recorder(list[httpx.Request]):
    """Every request a fake API received, in order."""

    @property
    def only(self) -> httpx.Request:
        assert len(self) == 1, f"expected exactly one request, got {len(self)}"
        return self[0]


def body(request: httpx.Request) -> Any:
    """The JSON body ``request`` carried, or ``None``."""
    return json.loads(request.content) if request.content else None


def respond(
    status: int = 200, payload: Any = None, *, headers: dict[str, str] | None = None
) -> Handler:
    """A fake API answering every request with ``status`` and ``payload``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(status, headers=headers)
        if isinstance(payload, (str, bytes)):
            return httpx.Response(status, content=payload, headers=headers)
        return httpx.Response(status, json=payload, headers=headers)

    return handler


def recording(handler: Handler, recorder: Recorder) -> httpx.MockTransport:
    """A transport that records each request, then lets ``handler`` answer it."""

    def record(request: httpx.Request) -> httpx.Response:
        request.read()
        recorder.append(request)
        return handler(request)

    return httpx.MockTransport(record)
