# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Type aliases and sentinels shared across the SDK."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Final, TypeAlias, final

import httpx

__all__ = [
    "NOT_GIVEN",
    "AsyncCredential",
    "AsyncTokenProvider",
    "Credential",
    "EntitlementValueInput",
    "NotGiven",
    "TimeoutTypes",
    "TokenProvider",
]

TokenProvider: TypeAlias = Callable[[], str]
"""A callable returning the token to send.

It is called before every request, so a rotated credential is picked up without rebuilding
the client.
"""

AsyncTokenProvider: TypeAlias = Callable[[], str | Awaitable[str]]
"""A :data:`TokenProvider` that may also be a coroutine function."""

Credential: TypeAlias = str | TokenProvider
AsyncCredential: TypeAlias = str | AsyncTokenProvider

TimeoutTypes: TypeAlias = float | httpx.Timeout | None
"""Seconds, an :class:`httpx.Timeout`, or ``None`` for no timeout at all."""

EntitlementValueInput: TypeAlias = bool | int | float | Mapping[str, Any]
"""A value to grant: ``True``/``False`` for BOOLEAN, a number for NUMBER (``-1`` is unlimited),
a mapping for CONFIG."""


@final
class NotGiven:
    """The type of :data:`NOT_GIVEN`, which tells "not passed" apart from an explicit ``None``."""

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN: Final = NotGiven()
